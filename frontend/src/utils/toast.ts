export type AppToastType = 'success' | 'error' | 'info'

export interface AppToastEventDetail {
  type: AppToastType
  message: string
}

export function emitAppToast(detail: AppToastEventDetail): void {
  window.dispatchEvent(new CustomEvent<AppToastEventDetail>('app-toast', { detail }))
}
