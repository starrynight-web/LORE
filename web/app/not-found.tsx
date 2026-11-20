import Link from "next/link"
import { SiteHeader } from "@/components/site-header"
import { SiteFooter } from "@/components/site-footer"

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col bg-[var(--background)] text-[var(--foreground)]">
      <SiteHeader />
      <main className="flex-1 flex flex-col items-center justify-center p-6 text-center space-y-4">
        <div className="p-3 rounded-2xl bg-[var(--card)] border border-[var(--border)] text-3xl font-mono font-bold text-[#7c6fd6]">
          404
        </div>
        <h1 className="text-2xl font-bold">Page Not Found</h1>
        <p className="text-sm text-[var(--muted-foreground)] max-w-md">
          The requested documentation or page does not exist.
        </p>
        <Link
          href="/enterprise/docs"
          className="px-4 py-2 rounded-xl bg-[#7c6fd6] hover:bg-[#5f52c4] text-white text-xs font-semibold transition-all shadow-sm"
        >
          Go to Enterprise Docs →
        </Link>
      </main>
      <SiteFooter />
    </div>
  )
}
