"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { tokenStore } from "@/lib/api";

export default function Nav() {
  const router = useRouter();
  return (
    <nav className="nav">
      <strong>Inbox Triage Agent</strong>
      <Link href="/">Inbox</Link>
      <Link href="/drafts">Drafts queue</Link>
      <button
        onClick={() => {
          tokenStore.clear();
          router.push("/login");
        }}
      >
        Sign out
      </button>
    </nav>
  );
}
