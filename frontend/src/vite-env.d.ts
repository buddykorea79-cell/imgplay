/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 백엔드 API 절대 주소. 비우면 같은 출처의 `/api`를 씁니다. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
