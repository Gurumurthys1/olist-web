// All settings come from .env.local (see .env.example), so no ID is hard-coded.
const env = import.meta.env

export const config = {
  region: env.VITE_AWS_REGION || 'us-east-1',
  userPoolId: env.VITE_COGNITO_USER_POOL_ID || '',
  clientId: env.VITE_COGNITO_CLIENT_ID || '',
  cognitoDomain: (env.VITE_COGNITO_DOMAIN || '').replace(/\/$/, ''),
  redirectUri: env.VITE_REDIRECT_URI || window.location.origin,
  apiUrl: (env.VITE_API_URL || '').replace(/\/$/, ''),
}

export const isConfigured = Boolean(config.userPoolId && config.clientId && config.cognitoDomain)

// Settings for react-oidc-context (Cognito's recommended setup for single-page apps)
export const oidcConfig = {
  authority: `https://cognito-idp.${config.region}.amazonaws.com/${config.userPoolId}`,
  client_id: config.clientId,
  redirect_uri: config.redirectUri,
  response_type: 'code',
  scope: 'openid email',
  // remove ?code=... from the address bar after login
  onSigninCallback: () => window.history.replaceState({}, document.title, window.location.pathname),
}
