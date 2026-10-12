export function normalizeSearch(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es").replace(/[_\s]+/g," ").trim();
}
export function matchesPropertySearch(item: {title:string;description?:string;comuna?:string}, query:string): boolean {
  const words=normalizeSearch(`${item.title} ${item.comuna??""} ${item.description??""}`).split(/[^a-z0-9]+/);
  return normalizeSearch(query).split(/[^a-z0-9]+/).filter(Boolean).every(term=>words.includes(term));
}
