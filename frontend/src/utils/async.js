export async function optionalLoad(loader, fallback = null) {
  try {
    return await loader()
  } catch {
    return fallback
  }
}
