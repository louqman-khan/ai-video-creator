import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, ApiError, type Account } from "./api/client";
import { useAuth } from "./store/auth";
import { useLang } from "./i18n";
import { useProjects } from "./store/projects";

const local: Account = { mode: "local", signups: "open", require_verification: true, user: { id: "local", email: null, admin: true } };
const hostedOut: Account = { mode: "hosted", signups: "open", require_verification: true, user: null };
const hostedIn: Account = { ...hostedOut, user: { id: "u1", email: "ann@example.com", admin: false, verified: true }, usage: { projects: 1, max_projects: 20, storage_bytes: 5e6, max_storage_bytes: 5e9, max_exports_per_day: 10 } };

/** the projects page greets the person (by the hour) instead of saying "Projects" */
const GREETING = /Good (morning|afternoon|evening)|Working late/;
const open = (path = "/") => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

beforeEach(() => {
  vi.restoreAllMocks();
  useAuth.setState({ account: null, error: null });
  useLang.setState({ lang: "en" });
  useProjects.setState({ projects: [], loading: false, error: null });
  vi.spyOn(api, "listProjects").mockResolvedValue([]);
  vi.spyOn(api, "storage").mockRejectedValue(new Error("none"));
});

describe("App and accounts", () => {
  it("local mode: no login, no account menu", async () => {
    vi.spyOn(api, "account").mockResolvedValue(local);
    open();
    expect(await screen.findByRole("heading", { name: GREETING })).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { name: GREETING })).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { name: GREETING })).toBeInTheDocument();
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
    expect(signup).toHaveBeenCalledWith({ email: "new@example.com", password: "a long passphrase here", invite: "beta", terms: true, lang: "en" });
    expect(await screen.findByRole("status")).toHaveTextContent("An e-mail is on its way.");
  });

  it("closed sign-ups say so", async () => {
    vi.spyOn(api, "account").mockResolvedValue({ ...hostedOut, signups: "closed" });
    open("/signup");
    expect(await screen.findByRole("heading", { name: "Sign-ups are closed" })).toBeInTheDocument();
  });

  it("there is no confirmation link page any more: an old /verify link ends on the log-in page", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    open("/verify?token=abc123");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("the empty fields show what to type and the password hint says 6 characters", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    open("/signup");
    expect(await screen.findByPlaceholderText("name@example.com")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("At least 6 characters")).toBeInTheDocument();
    expect(screen.getByText(/At least 6 characters\. A few random words/)).toBeInTheDocument();
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

  it("after sign-up the six digits from the e-mail confirm the address and the person lands on the dashboard, logged in", async () => {
    const account = vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    vi.spyOn(api, "signup").mockResolvedValue({ message: "An e-mail is on its way." });
    const code = vi.spyOn(api, "verifyCode").mockRejectedValueOnce(new Error("That code is wrong or has expired. Check the e-mail or ask for a new one.")).mockResolvedValue({ message: "Your e-mail address is confirmed. You can log in now." });
    const login = vi.spyOn(api, "login").mockResolvedValue({});
    open("/signup");
    await userEvent.type(await screen.findByLabelText("E-mail"), "New@Example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase here");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    const box = await screen.findByLabelText("6-digit code");
    expect(screen.getByText("new@example.com")).toBeInTheDocument();
    await userEvent.type(box, "123 456");                                              // spaces and a wrong code first
    expect(code).toHaveBeenCalledWith("new@example.com", "123456");                    // it sends itself at the sixth digit
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong or has expired");
    account.mockResolvedValue(hostedIn);                                                // the server will know the person after the log-in
    await userEvent.type(screen.getByLabelText("6-digit code"), "654321");
    await waitFor(() => expect(login).toHaveBeenCalledWith({ email: "New@Example.com", password: "a long passphrase here" }));
    expect(await screen.findByRole("heading", { name: GREETING })).toBeInTheDocument();   // no extra click: straight to the projects page
  });

  it("if the automatic log-in after the code does not work, the person gets the plain confirmed page with a log-in button", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    vi.spyOn(api, "signup").mockResolvedValue({ message: "An e-mail is on its way." });
    vi.spyOn(api, "verifyCode").mockResolvedValue({ message: "Your e-mail address is confirmed. You can log in now." });
    vi.spyOn(api, "login").mockRejectedValue(new Error("E-mail or password is wrong."));
    open("/signup");
    await userEvent.type(await screen.findByLabelText("E-mail"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase here");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    expect(await screen.findByRole("link", { name: "Go to log in" })).toHaveAttribute("href", "/login");
  });

  it("a log-in that is refused because the address is not confirmed offers the code box and a new e-mail", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    vi.spyOn(api, "login").mockRejectedValue(new ApiError("Confirm your e-mail address first: open the link we sent you.", 403));
    open("/login");
    await userEvent.type(await screen.findByLabelText("E-mail"), "ann@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByLabelText("6-digit code")).toBeInTheDocument();
    const resend = vi.spyOn(api, "resend").mockResolvedValue({ message: "ok" });
    await userEvent.click(screen.getByRole("button", { name: "Send a new e-mail" }));         // the old code may have expired: a new one can be asked for at once
    expect(resend).toHaveBeenCalledWith("ann@example.com", "en");
    expect(await screen.findByRole("button", { name: /Send a new e-mail \(\d+\)/ })).toBeDisabled();   // and then a short wait: nobody can make the site send e-mail in a loop
  });

  it("the language switch turns the sign-in pages into Urdu, right to left, and is remembered", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    const { container } = open("/login");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "اردو" }));
    expect(await screen.findByRole("heading", { name: "لاگ اِن" })).toBeInTheDocument();
    expect(screen.getByLabelText("ای میل")).toBeInTheDocument();
    expect(screen.getByText("پاس ورڈ بھول گئے؟")).toBeInTheDocument();
    expect(container.querySelector(".auth-split")).toHaveAttribute("dir", "rtl");
    expect(window.localStorage.getItem("avc-lang")).toBe("ur");
    await userEvent.click(screen.getByRole("button", { name: "English" }));
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
    expect(container.querySelector(".auth-split")).toHaveAttribute("dir", "ltr");
  });

  it("the chosen language goes to the server so the e-mail comes in the same language", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    const forgot = vi.spyOn(api, "forgotPassword").mockResolvedValue({ message: "If that is possible, an e-mail is on its way. Check your inbox (and the spam folder)." });
    useLang.setState({ lang: "ur" });
    open("/forgot");
    await userEvent.type(await screen.findByLabelText("ای میل"), "ann@example.com");
    await userEvent.click(screen.getByRole("button", { name: "مجھے لنک بھیجیں" }));
    expect(forgot).toHaveBeenCalledWith("ann@example.com", "ur");
    expect(await screen.findByRole("status")).toHaveTextContent("اگر یہ ممکن ہوا");     // even the server's answer is shown in Urdu
  });

  it("sign-up says so when the address already has an account and offers log in and password reset", async () => {
    vi.spyOn(api, "account").mockResolvedValue(hostedOut);
    vi.spyOn(api, "signup").mockRejectedValue(new ApiError("This e-mail already has an account. Log in, or reset your password if you forgot it.", 409));
    open("/signup");
    await userEvent.type(await screen.findByLabelText("E-mail"), "ann@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase here");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already has an account");
    expect(screen.getAllByRole("link", { name: "Log in" }).every((l) => l.getAttribute("href") === "/login")).toBe(true);
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot");
  });
});

