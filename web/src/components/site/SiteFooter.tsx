import { cn } from '@/lib/utils'

export const REPO_URL = 'https://github.com/KyleNaluan/blessings-abound'

// The column it lines up with: the public pages' one by default, or the signed-in page's.
export function SiteFooter({ wrap = 'page-wrap' }: { wrap?: string }) {
  return (
    <footer className="band pt-8 pb-10 text-[0.9375rem]">
      <div className={cn(wrap, 'flex flex-wrap justify-between gap-x-8 gap-y-4')}>
        <p className="max-w-[38rem]">
          A student proof of concept inspired by Blessings Abound for Hack-A-Roo Fall 2026. It is
          not an official Blessings Abound product.
        </p>
        <p className="max-w-[38rem]">
          &copy; {new Date().getFullYear()} Turnstone team. <a href={REPO_URL}>GitHub</a>
        </p>
      </div>
    </footer>
  )
}
