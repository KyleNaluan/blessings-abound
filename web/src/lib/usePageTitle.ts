import { useEffect } from 'react'

// Sets the browser tab title, as "<page> - Turnstone", or "Turnstone" alone for the landing page.
export function usePageTitle(page?: string) {
  useEffect(() => {
    document.title = page ? `${page} - Turnstone` : 'Turnstone'
  }, [page])
}
