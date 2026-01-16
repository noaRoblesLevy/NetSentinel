import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SiteState {
  selectedSiteId: string | null
  setSelectedSiteId: (siteId: string | null) => void
}

export const useSite = create<SiteState>()(
  persist(
    (set) => ({
      selectedSiteId: null,
      setSelectedSiteId: (siteId) => set({ selectedSiteId: siteId }),
    }),
    {
      name: 'site-storage',
    }
  )
)
