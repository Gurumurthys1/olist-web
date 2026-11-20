import { useAuth } from 'react-oidc-context'
import { config } from './config'

// The logged-in user, their Cognito groups, and a logout that also ends the Cognito session.
export function useUser() {
  const auth = useAuth()
  const profile: Record<string, unknown> = auth.user?.profile ?? {}
  const groups = (profile['cognito:groups'] as string[] | undefined) ?? []

  const logout = async () => {
    await auth.removeUser()
    const url = new URL(`${config.cognitoDomain}/logout`)
    url.searchParams.set('client_id', config.clientId)
    url.searchParams.set('logout_uri', config.redirectUri)
    window.location.href = url.toString()
  }

  return {
    email: (profile.email as string | undefined) ?? '',
    groups,
    isAdmin: groups.includes('admin'),
    idToken: auth.user?.id_token ?? '',
    logout,
  }
}
