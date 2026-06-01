import { optionalRequest, request } from '@/api/request'
import { getModelDisplayName } from '@/utils/modelProfile'

export async function getModelProfile() {
  return optionalRequest('/model-config/profile', {}, { display_name: getModelDisplayName() })
}

export async function getModelConfig() {
  return request('/model-config')
}

export async function updateModelConfig(payload) {
  return request('/model-config', {
    method: 'PUT',
    body: JSON.stringify({
      display_name: payload.display_name,
      auth_json: payload.auth_json,
      config_toml: payload.config_toml,
    }),
  })
}
