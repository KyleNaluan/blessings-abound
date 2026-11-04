import { Navigate, Route, Routes } from 'react-router'

import { AuthProvider } from '@/auth/AuthProvider'
import { RequireAuth } from '@/auth/RequireAuth'
import { AppraisalPage } from '@/pages/AppraisalPage'
import { ChoosePasswordPage } from '@/pages/ChoosePasswordPage'
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage'
import { HomePage } from '@/pages/HomePage'
import { LandingPage } from '@/pages/LandingPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SignInPage } from '@/pages/SignInPage'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/sign-in" element={<SignInPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/choose-password" element={<ChoosePasswordPage />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/app/appraise"
          element={
            <RequireAuth>
              <AppraisalPage />
            </RequireAuth>
          }
        />
        <Route
          path="/app/settings"
          element={
            <RequireAuth>
              <SettingsPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
