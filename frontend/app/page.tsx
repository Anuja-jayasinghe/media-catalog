import { GuestCatalog, SignedCatalog } from "./catalog";

export default function Home() {
  const clerkReady = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);
  return clerkReady ? <SignedCatalog /> : <GuestCatalog />;
}
