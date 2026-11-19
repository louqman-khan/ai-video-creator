import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import type { Account, Credits } from "../api/client";
import { useAuth } from "../store/auth";
import { CreditsCard } from "./CreditsCard";

const credits = (over: Partial<Credits> = {}): Credits => ({ plan: "Free", monthly: 10, used: 6, remaining: 4, resets_on: "2026-12-01", unlimited: false, minutes_per_credit: 1, ...over });
const account = (c?: Credits): Account => ({ mode: "hosted", signups: "open", require_verification: true,
  user: { id: "u", email: "a@b.co", admin: false }, usage: c ? { credits: c, projects: 1, max_projects: 20, storage_bytes: 0, max_storage_bytes: 1, max_exports_per_day: 10 } : undefined });
const show = () => render(<MemoryRouter><CreditsCard /></MemoryRouter>);

beforeEach(() => useAuth.setState({ account: null, error: null }));

describe("CreditsCard", () => {
  it("shows the plan, what is used, what is left and when it renews", () => {
    useAuth.setState({ account: account(credits()) });
    show();
    expect(screen.getByText("Free plan")).toBeInTheDocument();
    expect(screen.getByText("6 of 10 video credits used this month.")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Credits used" })).toHaveAttribute("aria-valuenow", "6");
    expect(screen.getByText(/4 left · renews/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Manage plan/ })).toHaveAttribute("href", "/account");
  });
  it("says so for an administrator and shows nothing when the server sent no credits", () => {
    useAuth.setState({ account: account(credits({ unlimited: true, used: 0, remaining: 10 })) });
    const { container, unmount } = show();
    expect(screen.getByText(/Unlimited \(administrator\)/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    unmount();
    useAuth.setState({ account: account() });
    expect(render(<MemoryRouter><CreditsCard /></MemoryRouter>).container).toBeEmptyDOMElement();
    void container;
  });
});
