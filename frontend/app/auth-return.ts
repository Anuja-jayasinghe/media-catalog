export function safeReturnTo(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  return value;
}

export function authHref(mode: "sign-in" | "sign-up", returnTo: string): string {
  return `/${mode}?${new URLSearchParams({ return_to: returnTo })}`;
}

export function titleReturnTo(id: string): string {
  return `/?${new URLSearchParams({ title: id })}`;
}
