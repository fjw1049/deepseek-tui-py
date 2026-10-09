"""Read bounded element context at a viewport point without clicking the page."""

import json


async def pick_element(client, x: float, y: float) -> dict:
    result = await client.send(
        "Runtime.evaluate",
        {
            "expression": """(([x, y]) => {
              let el = document.elementFromPoint(x, y);
              while (el?.shadowRoot?.elementFromPoint(x, y)) {
                const child = el.shadowRoot.elementFromPoint(x, y);
                if (child === el) break;
                el = child;
              }
              if (!el || ['HTML', 'HEAD', 'SCRIPT', 'STYLE'].includes(el.tagName)) return null;
              const label = node => node.tagName.toLowerCase() +
                (node.id ? '#' + CSS.escape(node.id) : '');
              const selector = node => {
                const parts = [];
                for (let n = node; n?.nodeType === 1; n = n.parentElement) {
                  let part = label(n);
                  if (!n.id && n.parentElement) {
                    const siblings = [...n.parentElement.children]
                      .filter(s => s.tagName === n.tagName);
                    if (siblings.length > 1)
                      part += ':nth-of-type(' + (siblings.indexOf(n) + 1) + ')';
                  }
                  parts.unshift(part);
                  if (n.id) break;
                }
                return parts.join(' > ').slice(0, 500);
              };
              const ancestry = [];
              for (let p = el.parentElement; p && ancestry.length < 3; p = p.parentElement)
                ancestry.push(label(p).slice(0, 500));
              const clone = el.cloneNode(true);
              for (const input of [clone, ...clone.querySelectorAll('input[type=password]')])
                if (input.type === 'password') input.removeAttribute('value');
              return {url: location.href, pick: {
                selector: selector(el), tagName: el.tagName.toLowerCase(), id: el.id.slice(0, 128),
                classes: [...el.classList].slice(0, 8).map(c => c.slice(0, 128)),
                textPreview: (el.innerText || el.textContent || '').slice(0, 200),
                htmlSnippet: clone.outerHTML.slice(0, 1200), ancestry
              }};
            })("""
            + json.dumps([x, y])
            + ")",
            "returnByValue": True,
        },
    )
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise ValueError("No selectable element at this point")
    return {"success": True, **value}
