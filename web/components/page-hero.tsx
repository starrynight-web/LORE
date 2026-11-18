export function PageHero({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pt-1">
      <div>
        <h1 className="text-[30px] font-bold tracking-[-0.03em] leading-[1.15]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1 text-[13px] text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="flex items-center gap-2.5">{action}</div> : null}
    </div>
  )
}
