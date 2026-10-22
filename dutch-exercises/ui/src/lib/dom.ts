// Tiny DOM helpers. Everything the agent writes is untrusted: it only ever reaches the page as text nodes or
// attribute values set through the DOM API. Nothing here uses innerHTML.

type Child = Node | string | number | false | null | undefined;
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs | null = null,
  ...children: (Child | Child[])[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") {
      el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    } else if (k === "class") {
      el.className = String(v);
    } else if (typeof v !== "function") {
      if (/^on/i.test(k)) continue; // never set inline handler attributes
      el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(el: Node, children: (Child | Child[])[]): void {
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

/** Inline markdown subset: **bold**, *italic* / _italic_, `code`. Anything else stays literal text. */
export function inline(text: string): Node[] {
  const out: Node[] = [];
  const re = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\*([^*\n]+)\*|(?<![\p{L}\p{N}])_([^_\n]+)_(?![\p{L}\p{N}])/gu;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push(document.createTextNode(text.slice(last, m.index)));
    if (m[1] !== undefined) out.push(h("strong", null, m[1]));
    else if (m[2] !== undefined) out.push(h("code", null, m[2]));
    else out.push(h("em", null, m[3] ?? m[4]));
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

/** Block markdown subset: blank-line separated paragraphs and "- " / "* " bullet lists (also right after a line). */
export function markdown(text: string): DocumentFragment {
  const frag = document.createDocumentFragment();
  const bullet = /^\s*[-*•]\s+/;
  for (const block of text.split(/\n\s*\n/)) {
    const lines = block.split("\n").map((l) => l.trimEnd()).filter((l) => l.trim());
    let p: HTMLParagraphElement | null = null;
    let ul: HTMLUListElement | null = null;
    for (const line of lines) {
      if (bullet.test(line)) {
        p = null;
        if (!ul) frag.appendChild((ul = h("ul")));
        ul.appendChild(h("li", null, inline(line.replace(bullet, ""))));
      } else {
        ul = null;
        if (p) p.appendChild(h("br"));
        else frag.appendChild((p = h("p")));
        append(p, inline(line));
      }
    }
  }
  return frag;
}

/** Only http(s) URLs are ever turned into links. */
export function safeUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function shuffle<T>(items: T[], rand: () => number = Math.random): T[] {
  const a = items.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
