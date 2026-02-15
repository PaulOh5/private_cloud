declare module '@novnc/novnc/lib/rfb' {
  type RfbEvent = Event & { detail?: { clean?: boolean } }

  export default class RFB {
    constructor(target: HTMLElement, urlOrChannel: string | unknown, options?: Record<string, unknown>)
    scaleViewport: boolean
    resizeSession: boolean
    disconnect(): void
    addEventListener(type: string, listener: (event: RfbEvent) => void): void
  }
}
