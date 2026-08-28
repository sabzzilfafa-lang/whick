/** 일괄 생성 실패 시 theme에 붙었던 오류 문구 제거 */
export function cleanTheme(theme: string | null | undefined): string {
  if (!theme) return "";
  const idx = theme.indexOf(" (생성 오류:");
  return idx >= 0 ? theme.slice(0, idx).trim() : theme;
}

export function hasGenerationError(theme: string | null | undefined): boolean {
  return Boolean(theme?.includes(" (생성 오류:"));
}
