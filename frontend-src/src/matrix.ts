// 2D affine transforms of SVG elements, computed from their `transform`
// attributes so that no rendering (getCTM) is needed.

/** [a, b, c, d, e, f] as in SVG `matrix(a b c d e f)`. */
export type Matrix = [number, number, number, number, number, number];

export const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

export function multiply(m: Matrix, n: Matrix): Matrix {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

export function invert(m: Matrix): Matrix {
  const det = m[0] * m[3] - m[1] * m[2];
  return [
    m[3] / det,
    -m[1] / det,
    -m[2] / det,
    m[0] / det,
    (m[2] * m[5] - m[3] * m[4]) / det,
    (m[1] * m[4] - m[0] * m[5]) / det,
  ];
}

export function apply(m: Matrix, x: number, y: number): [number, number] {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/** Parse a `transform` attribute (translate, scale, rotate, matrix). */
export function parseTransform(value: string | null): Matrix {
  let result: Matrix = IDENTITY;
  if (!value) return result;
  for (const [, name, args] of value.matchAll(/(\w+)\s*\(([^)]*)\)/g)) {
    const n = (args ?? "")
      .split(/[\s,]+/)
      .filter((part) => part !== "")
      .map(Number);
    let step: Matrix = IDENTITY;
    switch (name) {
      case "translate":
        step = [1, 0, 0, 1, n[0] ?? 0, n[1] ?? 0];
        break;
      case "scale":
        step = [n[0] ?? 1, 0, 0, n[1] ?? n[0] ?? 1, 0, 0];
        break;
      case "rotate": {
        const angle = ((n[0] ?? 0) * Math.PI) / 180;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        const [cx = 0, cy = 0] = [n[1], n[2]];
        step = multiply(
          multiply([1, 0, 0, 1, cx, cy], [cos, sin, -sin, cos, 0, 0]),
          [1, 0, 0, 1, -cx, -cy],
        );
        break;
      }
      case "matrix":
        if (n.length === 6) step = n as Matrix;
        break;
    }
    result = multiply(result, step);
  }
  return result;
}

/** Transform from the local system of an element to the system of `root`. */
export function toRoot(element: Element, root: Element): Matrix {
  const chain: Element[] = [];
  for (let node: Element | null = element; node && node !== root;) {
    chain.unshift(node);
    node = node.parentElement;
  }
  return chain.reduce<Matrix>(
    (m, node) => multiply(m, parseTransform(node.getAttribute("transform"))),
    IDENTITY,
  );
}
