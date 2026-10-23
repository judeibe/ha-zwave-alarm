const BAR = "animate-pulse rounded-lg bg-zinc-200 motion-reduce:animate-none dark:bg-zinc-800";

/** Placeholder rows shown while the first overview load is in flight. */
export const SkeletonList = ({ rows = 3 }: { rows?: number }) => (
  <div className="my-3 divide-y divide-zinc-200/70 overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-black/5 dark:divide-white/10 dark:bg-zinc-900 dark:ring-white/10">
    {Array.from({ length: rows }, (_, i) => (
      <div key={i} className="flex min-h-14 items-center gap-3 px-4 py-2.5">
        <div className={`${BAR} size-9 rounded-xl`} />
        <div className="flex-1 space-y-2">
          <div className={`${BAR} h-4 w-1/2`} />
          <div className={`${BAR} h-3 w-1/3`} />
        </div>
      </div>
    ))}
  </div>
);
