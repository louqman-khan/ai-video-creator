import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Account, type AdminUser, type Credits } from "../api/client";
import { useAuth } from "../store/auth";
import { AdminPage } from "./AdminPage";

const credits = (over: Partial<Credits> = {}): Credits => ({ plan: "Free", monthly: 10, used: 3, remaining: 7, resets_on: "2026-12-01", unlimited: false, minutes_per_credit: 1, ...over });
const user = (over: Partial<AdminUser> = {}): AdminUser => ({ id: "u1", email: "ann@example.com", role: "user", verified: true, disabled: false, created_at: 1_700_000_000, last_login: null, projects: 2, storage_bytes: 5e8, credits: credits(), ...over });
const account = (admin: boolean, mode: "local" | "hosted" = "hosted"): Account => ({ mode, signups: "open", require_verification: true, user: { id: "me", email: "boss@example.com", admin } });
const show = () => render(<MemoryRouter initialEntries={["/admin"]}><Routes><Route path="/admin" element={<AdminPage />} /><Route path="/" element={<p>home</p>} /></Routes></MemoryRouter>);

beforeEach(() => {
  vi.restoreAllMocks();
  useAuth.setState({ account: account(true), error: null });
});

describe("AdminPage", () => {
  it("lists the accounts with their use", async () => {
    vi.spyOn(api, "adminUsers").mockResolvedValue([user(), user({ id: "u2", email: "boss@example.com", role: "admin", credits: credits({ unlimited: true }) })]);
    show();
    expect(await screen.findByText("ann@example.com")).toBeInTheDocument();
    expect(screen.getByText("3 used · 7 left")).toBeInTheDocument();
    expect(screen.getAllByText("500 MB")).toHaveLength(2);
    expect(screen.getByText("Unlimited")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 accounts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Switch off boss/ })).not.toBeInTheDocument();      // an administrator cannot be switched off
    await userEvent.type(screen.getByLabelText("Find an account"), "ann");
    expect(screen.getByText("1 of 2 accounts")).toBeInTheDocument();
  });

  it("adds bonus credits and shows the answer", async () => {
    vi.spyOn(api, "adminUsers").mockResolvedValueOnce([user()]).mockResolvedValue([user({ credits: credits({ remaining: 12, bonus: 5 }) })]);
    const give = vi.spyOn(api, "adminGiveCredits").mockResolvedValue(credits({ remaining: 12, bonus: 5 }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Add credits to ann@example.com" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));                              // the box starts at 5
    await waitFor(() => expect(give).toHaveBeenCalledWith("u1", 5));
    expect(await screen.findByRole("status")).toHaveTextContent("Added 5 credits to ann@example.com.");
    expect(await screen.findByText(/includes 5 bonus/)).toBeInTheDocument();
  });

  it("switches an account off only after asking, and shows server errors", async () => {
    vi.spyOn(api, "adminUsers").mockResolvedValue([user()]);
    const off = vi.spyOn(api, "adminSetDisabled").mockResolvedValue({ id: "u1", disabled: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    show();
    const b = await screen.findByRole("button", { name: "Switch off ann@example.com" });
    await userEvent.click(b);
    expect(off).not.toHaveBeenCalled();
    await userEvent.click(b);
    await waitFor(() => expect(off).toHaveBeenCalledWith("u1", true));
    expect(confirm).toHaveBeenCalledTimes(2);
    vi.spyOn(api, "adminGiveCredits").mockRejectedValue(new Error("This account only has 0 bonus credits to take back."));
    await userEvent.click(await screen.findByRole("button", { name: "Add credits to ann@example.com" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("0 bonus credits");
  });

  it("sends everyone who is not an administrator of a hosted site back home", async () => {
    useAuth.setState({ account: account(false) });
    vi.spyOn(api, "adminUsers").mockResolvedValue([]);
    show();
    expect(await screen.findByText("home")).toBeInTheDocument();
  });
});
