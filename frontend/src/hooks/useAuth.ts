import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'
import api from '@/lib/api'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,  // Will be verified on checkAuth
      isLoading: true,  // Start with loading since we need to verify session

      login: async (email: string, password: string) => {
        set({ isLoading: true })
        try {
          const response = await api.login({ email, password })
          set({
            user: response.user,
            isAuthenticated: true,
            isLoading: false,
          })
        } catch (error) {
          set({ isLoading: false })
          throw error
        }
      },

      logout: async () => {
        try {
          await api.logout()
        } finally {
          set({
            user: null,
            isAuthenticated: false,
          })
        }
      },

      checkAuth: async () => {
        // Always try to verify session via API call
        // The httpOnly cookie will be sent automatically
        set({ isLoading: true })
        try {
          const user = await api.getCurrentUser()
          api.setAuthenticated(true)
          set({
            user,
            isAuthenticated: true,
            isLoading: false,
          })
        } catch {
          api.setAuthenticated(false)
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          })
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ user: state.user }),
    }
  )
)
