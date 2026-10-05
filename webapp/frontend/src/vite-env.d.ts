/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend API base, e.g. https://smugglers.onrender.com/api. Unset: same origin (/api). */
  readonly VITE_API_URL?: string
}
