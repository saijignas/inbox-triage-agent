import type { Metadata } from "next";
import Nav from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Inbox Triage Agent",
  description: "AI-assisted email triage. Drafts are never sent without human approval.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main>{children}</main>
      </body>
    </html>
  );
}
