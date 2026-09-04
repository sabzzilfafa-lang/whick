/** Whick customer runtime — KST(Asia/Seoul) SSOT */
export const KST = 'Asia/Seoul';

export function kstNow() {
  return new Date();
}

export function kstTimestamp(d = kstNow()) {
  return d.toLocaleString('sv-SE', { timeZone: KST }).slice(0, 19);
}

export function kstIso(d = kstNow()) {
  return `${kstTimestamp(d).replace(' ', 'T')}+09:00`;
}
