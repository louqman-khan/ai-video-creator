import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, type Account } from "./api/client";
import { useAuth } from "./store/auth";
import { useProjects } from "./store/projects";

const local: Account = { mode: "local", signups: "open", require_verification: true, user: { id: "local", email: null, admin: true } };
const hostedOut: Account = { mode: "hosted", signups: "open", require_verification: true, user: null };
const hostedIn: Account = { ...hostedOut, user: { id: "u1", email: "ann@example.com", admin: false, verified: true }, usage: { projects: 1, max_projects: 20, storage_bytes: 5e6, max_storage_bytes: 5e9, max_exports_per_day: 10 } };

const open = (path = "/") => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

beforeEach(() => {
  vi.restoreAllMocks();
  useAuth.setState({ account: null, error: null });
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.spyOn(api, "listProjects").mockResolvedValue([]);
  vi.spyOn(api, "storage").mockRejectedValue(new Error("none"));
});

describe("App and accounts", () => {
  it("local mode: no login, no account menu", async () => {
    vi.spyOn(api, "account").mockResolvedValue(local);
    open();
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log out" })).not.toBeInTheDocument();
  });

  it("hosted mode, not logged in: every page leads to the log-in page, and /terms stays readable", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    open("/projects/abc");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Projects" })).not.toBeInTheDocument();
  });

  it("logs in and lands on the projects, then logs out", async () => {
    const account = vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    const login = vi.spyOn(api, "login").mockResolvedValue({});
    open("/login");
    await userEvent.type(await screen.findByLabelText("E-mail"), "ann@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    account.mockResolvedValue(hostedIn);
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith({ email: "ann@example.com", password: "correct horse battery" });
    expect(screen.getByRole("link", { name: "ann@example.com" })).toBeInTheDocument();
    const logout = vi.spyOn(api, "logout").mockResolvedValue({});
    account.mockResolvedValue(hostedOut);
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(logout).toHaveBeenCalled());
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("shows the server's reason when the log-in fails and never the password", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    vi.spyOn(api, "login").mockRejectedValue(new Error("E-mail or password is wrong."));
    open("/login");
    await userEvent.type(await screen.findByLabelText("E-mail"), "ann@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "nope nope nope");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail or password is wrong.");
  });

  it("the session ending in the background sends the person to the log-in page", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedIn);
    open("/");
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    window.dispatchEvent(new Event("avc:unauthorized"));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("sign-up needs the terms, shows the invitation field only for invite-only sites, and tells the person to check e-mail", async () => {
    vi.spyOn(api, "account").mockResolvedValue({ ...hostedOut, signups: "invite" });
    const signup = vi.spyOn(api, "signup").mockResolvedValue({ message: "An e-mail is on its way." });
    open("/signup");
    await userEvent.type(await screen.findByLabelText("E-mail"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase here");
    await userEvent.type(screen.getByLabelText("Invitation code"), "beta");
    const button = screen.getByRole("button", { name: "Create account" });
    expect(button).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(button);
    expect(signup).toHaveBeenCalledWith({ email: "new@example.com", password: "a long passphrase here", invite: "beta", terms: true });
    expect(await screen.findByRole("status")).toHaveTextContent("An e-mail is on its way.");
  });

  it("closed sign-ups say so", async () => {
    vi.spyOn(api, "account").mockResolvedValue({ ...hostedOut, signups: "closed" });
    open("/signup");
    expect(await screen.findByRole("heading", { name: "Sign-ups are closed" })).toBeInTheDocument();
  });

  it("the verify link asks for a click, confirms, and offers the log-in", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    const verify = vi.spyOn(api, "verifyEmail").mockResolvedValue({ message: "Your e-mail address is confirmed. You can log in now." });
    open("/verify?token=abc123");
    await userEvent.click(await screen.findByRole("button", { name: "Confirm my address" }));
    expect(verify).toHaveBeenCalledWith("abc123");
    expect(await screen.findByRole("status")).toHaveTextContent("confirmed");
    expect(screen.getByRole("link", { name: "Log in" })).toBeInTheDocument();
  });

  it("the reset page changes the password with the token from the link", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    const reset = vi.spyOn(api, "resetPassword").mockResolvedValue({ message: "Your password has been changed. Log in with the new one." });
    open("/reset?token=tok9");
    await userEvent.type(await screen.findByLabelText("New password"), "another long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(reset).toHaveBeenCalledWith("tok9", "another long passphrase");
    expect(await screen.findByRole("status")).toHaveTextContent("changed");
  });

  it("the account page shows the limits, offers the data download, and deleting needs the password", async () => {
    const account = vi.spyOn(api, "account").mockResolvedValue(hostedIn);
    const del = vi.spyOn(api, "deleteAccount").mockResolvedValue({ message: "deleted" });
    open("/account");
    expect(await screen.findByText(/Projects: 1 of 20/)).toBeInTheDocument();
    expect(screen.getByText(/Storage: 5 MB of 5\.0 GB/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download my data" })).toHaveAttribute("href", "/api/auth/export");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account…" }));
    const confirm = screen.getByRole("button", { name: "Delete everything" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Type your password to confirm"), "correct horse battery");
    account.mockResolvedValue(hostedOut);
    await userEvent.click(confirm);
    expect(del).toHaveBeenCalledWith("correct horse battery");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });
});
