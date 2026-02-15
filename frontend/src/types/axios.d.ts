import 'axios'

declare module 'axios' {
  export interface AxiosRequestConfig {
    _skipAuthRefresh?: boolean
  }

  export interface InternalAxiosRequestConfig {
    _skipAuthRefresh?: boolean
  }
}
