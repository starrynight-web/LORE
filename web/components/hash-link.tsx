"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import type { ComponentProps, MouseEvent } from "react"

import { getHashFromHref, scrollToHash } from "@/lib/scroll-to-hash"

type HashLinkProps = ComponentProps<typeof Link>

/**
 * Same-page hash links that actually scroll (Next.js Link often skips this)
 * and still work when navigating from other routes to `/#section`.
 */
export function HashLink({ href, onClick, children, ...props }: HashLinkProps) {
  const pathname = usePathname()
  const hrefStr = typeof href === "string" ? href : href.pathname || ""
  const hash = typeof href === "string" ? getHashFromHref(href) : null

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (e.defaultPrevented || !hash) return

    const targetPath =
      typeof href === "string"
        ? href.split("#")[0] || "/"
        : href.pathname || "/"

    const onTargetPage =
      pathname === targetPath ||
      (targetPath === "/" && (pathname === "/" || pathname === "")) ||
      (hrefStr.startsWith("#") && (pathname === "/" || pathname === ""))

    if (!onTargetPage) return

    e.preventDefault()
    // Let any pending paint settle, then scroll under sticky header (via scroll-margin)
    requestAnimationFrame(() => {
      scrollToHash(hash)
    })
  }

  return (
    <Link href={href} onClick={handleClick} {...props}>
      {children}
    </Link>
  )
}
