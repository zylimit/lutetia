// Who is signed in, as last answered by GET /api/v1/me (filled by the route guard in router.ts).
import { reactive } from 'vue'

export const session = reactive<{ account: string | null; checkFailed: boolean }>({
  account: null,
  checkFailed: false, // /me failed for a reason other than 401 (server down, offline): the shell says so instead of hiding it
})
