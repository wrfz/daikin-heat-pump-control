// The schematic: an SVG layout filled with the values of Home Assistant.

import { composeColor } from "./appearance";
import { formatValue, numericState, separatorIndex } from "./format";
import { localize } from "./localize";
import { apply, invert, multiply, toRoot, type Matrix } from "./matrix";
import type { Appearance, DashboardData, HomeAssistant } from "./types";
import {
  DEFAULT_FONT_SIZE,
  DEFAULT_OFFSET,
  GROUPS,
  LABEL_FONT_SIZE,
  NO_ERROR,
  VALUES,
  type GroupSpec,
} from "./values";

const NS = "http://www.w3.org/2000/svg";
// Width of a space at the label size; the gap after a value prefix is three.
const PREFIX_SPACE = 8.75;

interface RunRule {
  id: string;
  mode: "on" | "gt0" | "eq";
  value?: string | string[];
}

interface TempRule {
  id: string | string[];
  min: number;
  max: number;
}

interface Row {
  value: string | null;
  rect: SVGRectElement;
  height: number;
  text?: SVGTextElement;
  divider?: SVGLineElement;
}

interface Shown {
  row: Row;
  value: string;
  entity: HassEntity;
}

interface Leader {
  path: SVGPathElement;
  // Start point in the coordinates of the group, end point as in the layout.
  start: [number, number];
  end: string;
  toPath: Matrix;
}

interface Group {
  spec: GroupSpec;
  element: SVGGElement;
  frame?: SVGRectElement;
  top: number;
  slots: number[];
  rows: Row[];
  separator?: number;
  hasLabel: boolean;
  leaders: SVGPathElement[];
  bottomLeaders: Leader[];
}

interface LayoutStyle {
  radius?: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: string;
  text?: string;
  label?: string;
  ownStates: boolean;
}

const num = (element: Element, name: string): number =>
  parseFloat(element.getAttribute(name) ?? "0") || 0;

const create = <K extends keyof SVGElementTagNameMap>(
  name: K,
  attributes: Record<string, string> = {},
): SVGElementTagNameMap[K] => {
  const element = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, value);
  }
  return element;
};

const show = (element: Element | undefined, visible: boolean): void => {
  if (element) (element as SVGElement).style.display = visible ? "" : "none";
};

const parseJson = <T>(svg: Element, name: string): Record<string, T> => {
  try {
    return JSON.parse(svg.getAttribute(name) ?? "{}") as Record<string, T>;
  } catch {
    return {};
  }
};

const parseLine = (d: string): number[] =>
  (d.match(/-?[\d.]+/g) ?? []).map(Number);

export class Schema {
  readonly svg: SVGSVGElement;
  private readonly style: LayoutStyle;
  private readonly groups: Group[] = [];
  private readonly runMap: Record<string, RunRule>;
  private readonly tempVars: Record<string, TempRule>;

  constructor(
    source: string,
    appearance: Appearance,
    private readonly language: string,
  ) {
    const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
    const root = parsed.documentElement;
    if (root.tagName.toLowerCase() !== "svg")
      throw new Error("Not an SVG layout");
    this.svg = document.importNode(root, true) as unknown as SVGSVGElement;
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    this.svg.setAttribute("data-animations", "on");
    this.style = this.layoutStyle(appearance);
    this.runMap = parseJson<RunRule>(this.svg, "data-run-map");
    this.tempVars = parseJson<TempRule>(this.svg, "data-temp-vars");
    for (const spec of GROUPS) {
      const element = this.find(spec.id) as SVGGElement | null;
      if (element) this.groups.push(this.buildGroup(spec, element));
    }
  }

  private find(id: string): Element | null {
    return this.svg.querySelector(`[id="${id}"]`);
  }

  private layoutStyle(appearance: Appearance): LayoutStyle {
    const attr = (name: string): string | undefined =>
      this.svg.getAttribute(name) ?? undefined;
    const style: LayoutStyle = {
      radius: attr("data-box-radius"),
      fill: attr("data-box-fill"),
      stroke: attr("data-box-stroke"),
      strokeWidth: attr("data-box-stroke-width"),
      text: attr("data-text-color"),
      label: attr("data-label-color"),
      ownStates: this.svg.hasAttribute("data-own-state-style"),
    };
    const { box, text, background } = appearance;
    style.fill =
      composeColor(box?.fill, box?.fill_opacity, style.fill) ?? style.fill;
    style.stroke =
      composeColor(box?.border, box?.border_opacity, style.stroke) ??
      style.stroke;
    style.text =
      composeColor(text?.value_color, undefined, undefined) ?? style.text;
    style.label =
      composeColor(text?.label_color, undefined, undefined) ?? style.label;
    if (background?.show === false) {
      this.svg.setAttribute("data-bg", "off");
    } else {
      const color = composeColor(background?.color, undefined, undefined);
      if (color) this.svg.style.setProperty("--bg-color", color);
      if (background?.opacity !== undefined) {
        const opacity = Math.min(100, Math.max(0, background.opacity)) / 100;
        this.svg.style.setProperty("--bg-opacity", String(opacity));
      }
    }
    return style;
  }

  private boxStyle(rect: Element, fill: string): void {
    rect.setAttribute("fill", fill);
    rect.setAttribute("stroke", this.style.stroke ?? "#000000");
    rect.setAttribute("stroke-width", this.style.strokeWidth ?? "2px");
    if (this.style.radius !== undefined) {
      rect.setAttribute("rx", this.style.radius);
      rect.setAttribute("ry", this.style.radius);
    }
  }

  private buildGroup(spec: GroupSpec, element: SVGGElement): Group {
    const rects = [...element.querySelectorAll("rect")];
    const label = element.querySelector("rect[data-label]");
    const rowRects = rects
      .filter(
        (rect) => rect.hasAttribute("data-value") || /_val(ue)?$/.test(rect.id),
      )
      .sort((a, b) => num(a, "y") - num(b, "y"));
    const top = Math.min(...rects.map((rect) => num(rect, "y")));
    const rounded = parseFloat(this.style.radius ?? "0") > 0;
    const fill = this.style.fill ?? "none";
    const group: Group = {
      spec,
      element,
      top,
      slots: rowRects.map((rect) => num(rect, "y")),
      rows: [],
      hasLabel: label !== null,
      leaders: [
        ...this.svg.querySelectorAll<SVGPathElement>(
          `path[data-box="${spec.id}"]`,
        ),
      ],
      bottomLeaders: [],
    };
    const separator = parseFloat(element.getAttribute("data-sep") ?? "");
    if (Number.isFinite(separator)) group.separator = separator;

    if (spec.framed && rounded) {
      const left = Math.min(...rects.map((rect) => num(rect, "x")));
      const right = Math.max(
        ...rects.map((rect) => num(rect, "x") + num(rect, "width")),
      );
      const bottom = Math.max(
        ...rects.map((rect) => num(rect, "y") + num(rect, "height")),
      );
      const frame = create("rect", {
        id: `${spec.id}_rect`,
        x: String(left),
        y: String(top),
        width: String(right - left),
        height: String(bottom - top),
      });
      this.boxStyle(frame, fill);
      element.insertBefore(frame, element.firstChild);
      group.frame = frame;
    }
    if (label) {
      const text = this.createText(label, LABEL_FONT_SIZE);
      text.setAttribute("fill", this.style.label ?? "#808080");
      text.setAttribute("x", String(num(label, "x") + num(label, "width") / 2));
      text.setAttribute(
        "y",
        String(num(label, "y") + num(label, "height") / 2 + 3),
      );
      text.setAttribute("text-anchor", "middle");
      text.textContent = localize(
        this.language,
        `label.${label.getAttribute("data-label") ?? ""}`,
      );
      element.appendChild(text);
      if (group.frame) label.remove();
      else this.boxStyle(label, fill);
    }
    rowRects.forEach((rect, index) => {
      const row: Row = {
        value: rect.getAttribute("data-value"),
        rect,
        height: num(rect, "height"),
      };
      if (spec.framed) {
        if (group.frame) {
          rect.setAttribute("fill", "none");
          rect.setAttribute("stroke", "none");
          if (label || spec.info || index > 0) {
            row.divider = create("line", {
              x1: String(num(rect, "x")),
              x2: String(num(rect, "x") + num(rect, "width")),
              stroke: this.style.stroke ?? "#000000",
              "stroke-width": "1.5",
              "stroke-opacity": "0.6",
            });
            element.appendChild(row.divider);
          }
        } else {
          this.boxStyle(rect, fill);
        }
      }
      if (row.value) {
        row.text = this.createText(rect, spec.fontSize ?? DEFAULT_FONT_SIZE);
        row.text.id = `${rect.id}_text`;
        element.appendChild(row.text);
      }
      group.rows.push(row);
    });
    group.bottomLeaders = this.bottomLeaders(group);
    return group;
  }

  private bottomLeaders(group: Group): Leader[] {
    const inside = [
      ...group.element.querySelectorAll<SVGPathElement>(
        'path[data-edge="bottom"]',
      ),
    ];
    const outside = group.leaders.filter(
      (path) => path.getAttribute("data-edge") === "bottom",
    );
    const groupToRoot = toRoot(group.element, this.svg);
    return [...inside, ...outside].map((path) => {
      const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = parseLine(
        path.getAttribute("d") ?? "",
      );
      const toPath = inside.includes(path)
        ? ([1, 0, 0, 1, 0, 0] as Matrix)
        : multiply(invert(toRoot(path, this.svg)), groupToRoot);
      return {
        path,
        start: apply(invert(toPath), x1, y1),
        end: `${x2} ${y2}`,
        toPath,
      };
    });
  }

  private createText(box: Element, fontSize: number): SVGTextElement {
    const text = create("text", {
      "dominant-baseline": "middle",
      "stroke-width": "1",
      "font-size": String(fontSize),
    });
    const transform = box.getAttribute("transform");
    if (transform) text.setAttribute("transform", transform);
    return text;
  }

  /** Show the current states. */
  update(hass: HomeAssistant, data: DashboardData): void {
    const entityOf = (id: string): string | undefined => data.entities[id];
    const stateOf = (id: string) => {
      const entityId = entityOf(id);
      return entityId ? hass.states[entityId] : undefined;
    };
    for (const group of this.groups)
      this.updateGroup(group, hass, data, stateOf);
    this.updateRunMap(stateOf);
    this.updateTempVars(stateOf);
    this.updateValves(stateOf);
    for (const symbol of this.svg.querySelectorAll("[data-more-info]")) {
      const entityId = entityOf(symbol.getAttribute("data-more-info") ?? "");
      if (entityId && hass.states[entityId]) {
        symbol.setAttribute("data-entity", entityId);
        symbol.setAttribute("cursor", "pointer");
      } else {
        symbol.removeAttribute("data-entity");
        symbol.removeAttribute("cursor");
      }
    }
  }

  private updateGroup(
    group: Group,
    hass: HomeAssistant,
    data: DashboardData,
    stateOf: (id: string) => HassEntity | undefined,
  ): void {
    let visible: Shown[] = [];
    for (const row of group.rows) {
      const entity = row.value !== null ? stateOf(row.value) : undefined;
      if (row.value !== null && entity)
        visible.push({ row, value: row.value, entity });
    }
    if (group.spec.info) {
      const order = data.info;
      visible = visible
        .filter((item) => order.includes(item.value))
        .sort((a, b) => order.indexOf(a.value) - order.indexOf(b.value));
    }
    show(group.element, visible.length > 0);
    for (const path of group.leaders) show(path, visible.length > 0);
    for (const row of group.rows) {
      const shown = visible.some((item) => item.row === row);
      show(row.rect, shown);
      show(row.text, shown);
      show(row.divider, shown);
    }
    if (visible.length === 0) return;

    let bottom = group.top;
    visible.forEach(({ row, value, entity }, index) => {
      const y = group.slots[index] ?? num(row.rect, "y");
      row.rect.setAttribute("y", String(y));
      if (row.divider) {
        row.divider.setAttribute("y1", String(y));
        row.divider.setAttribute("y2", String(y));
        show(row.divider, index > 0 || group.hasLabel);
      }
      if (row.text)
        this.updateText(group, row, row.text, value, y, hass, entity);
      bottom = y + row.height;
    });
    if (group.frame) {
      group.frame.setAttribute("height", String(bottom - group.top));
      for (const leader of group.bottomLeaders) {
        const [x, y] = apply(leader.toPath, leader.start[0], bottom);
        leader.path.setAttribute(
          "d",
          `M${x.toFixed(2)} ${y.toFixed(2)} L${leader.end}`,
        );
      }
    }
  }

  private updateText(
    group: Group,
    row: Row,
    text: SVGTextElement,
    value: string,
    y: number,
    hass: HomeAssistant,
    entity: HassEntity,
  ): void {
    const spec = VALUES[value] ?? { digits: 1 };
    const formatted = formatValue(hass, entity, spec);
    let state: string = formatted.state;
    if (
      value === ERROR_CODE &&
      state === "normal" &&
      entity.state !== NO_ERROR
    ) {
      state = "error";
    }
    const content = group.spec.info
      ? `${localize(this.language, `info.${value}`)} ${formatted.text}`
      : formatted.text;
    const prefix = spec.prefix
      ? localize(this.language, `prefix.${value}`)
      : undefined;
    this.setText(
      text,
      content,
      prefix,
      state === "normal" ? group.separator : undefined,
    );

    const rect = row.rect;
    const left =
      group.spec.alignLeft || rect.getAttribute("data-align") === "left";
    text.setAttribute(
      "x",
      String(left ? num(rect, "x") : num(rect, "x") + num(rect, "width") / 2),
    );
    text.setAttribute("text-anchor", left ? "start" : "middle");
    text.setAttribute(
      "y",
      String(y + row.height / 2 + (group.spec.offset ?? DEFAULT_OFFSET)),
    );
    text.setAttribute("data-entity", entity.entity_id);
    text.setAttribute("cursor", "pointer");
    text.setAttribute("data-state", state);
    // Layouts that style the states themselves only get the state.
    if (state === "normal" || !this.style.ownStates) {
      text.setAttribute(
        "fill",
        state === "normal"
          ? (this.style.text ?? "currentColor")
          : state === "error"
            ? "red"
            : "orange",
      );
    } else {
      text.removeAttribute("fill");
    }
  }

  /**
   * Text of a value; a prefix is drawn like a label. With a separator position
   * (`data-sep`) the part before the decimal separator ends there and the rest
   * starts there, so the rows of a box line up.
   */
  private setText(
    text: SVGTextElement,
    content: string,
    prefix: string | undefined,
    separator: number | undefined,
  ): void {
    const index = separator !== undefined ? separatorIndex(content) : -1;
    text.textContent = "";
    if (!prefix && index < 0) {
      text.textContent = content;
      return;
    }
    const span = (
      parent: Element,
      value: string,
      attributes: Record<string, string> = {},
    ) => {
      const tspan = create("tspan", attributes);
      tspan.textContent = value;
      parent.appendChild(tspan);
      return tspan;
    };
    const head =
      index >= 0
        ? span(text, "", { x: String(separator), "text-anchor": "end" })
        : text;
    if (prefix) {
      span(head, prefix, {
        "font-size": String(LABEL_FONT_SIZE),
        fill: this.style.label ?? "#808080",
      });
    }
    span(
      head,
      index >= 0 ? content.slice(0, index) : content,
      prefix ? { dx: String(3 * PREFIX_SPACE) } : {},
    );
    if (index >= 0) {
      span(text, content.slice(index), {
        x: String(separator),
        "text-anchor": "start",
      });
    }
  }

  // Elements named in data-run-map get data-state on/off/unknown; the CSS of
  // the layout animates or greys them.
  private updateRunMap(stateOf: (id: string) => HassEntity | undefined): void {
    for (const [elementId, rule] of Object.entries(this.runMap)) {
      const element = this.find(elementId);
      if (!element) continue;
      const state = stateOf(rule.id)?.state;
      let result = "unknown";
      if (
        state !== undefined &&
        state !== "unknown" &&
        state !== "unavailable"
      ) {
        const values = Array.isArray(rule.value) ? rule.value : [rule.value];
        const hit =
          rule.mode === "gt0"
            ? parseFloat(state) > 0
            : rule.mode === "eq"
              ? values.includes(state)
              : state === "on";
        result = hit ? "on" : "off";
      }
      element.setAttribute("data-state", result);
    }
  }

  // --k-* (0..1) from the first known value of a rule; the CSS of the layout
  // turns them into colours and speeds.
  private updateTempVars(
    stateOf: (id: string) => HassEntity | undefined,
  ): void {
    for (const [name, rule] of Object.entries(this.tempVars)) {
      const ids = Array.isArray(rule.id) ? rule.id : [rule.id];
      const value = ids
        .map((id) => numericState(stateOf(id)))
        .find((v) => v !== undefined);
      if (value !== undefined && rule.max !== rule.min) {
        const k = Math.min(
          1,
          Math.max(0, (value - rule.min) / (rule.max - rule.min)),
        );
        this.svg.style.setProperty(name, k.toFixed(3));
      } else {
        this.svg.style.removeProperty(name);
      }
    }
  }

  // Valve flaps turn with the position; the arrows show the open share.
  private updateValves(stateOf: (id: string) => HassEntity | undefined): void {
    const share = (id: string): number =>
      Math.min(1, Math.max(0, (numericState(stateOf(id)) ?? 0) / 100));
    const valves: [string, string, string, string][] = [
      [
        "dhw-flap",
        "dhw-open-arrows",
        "dhw-closed-arrows",
        "dhw_mixer_position",
      ],
      ["bpv-flap", "bpv-open-arrows", "bpv-closed-arrows", "bypass_valve"],
    ];
    for (const [flapId, openId, closedId, value] of valves) {
      const position = share(value);
      const flap = this.find(flapId);
      if (flap) {
        const [px = "0", py = "0"] = (
          flap.getAttribute("data-pivot") ?? "0 0"
        ).split(" ");
        const a0 = num(flap, "data-a0");
        const a1 = num(flap, "data-a1");
        flap.setAttribute(
          "transform",
          `rotate(${a0 + (a1 - a0) * position} ${px} ${py})`,
        );
      }
      const open = this.find(openId) as SVGElement | null;
      const closed = this.find(closedId) as SVGElement | null;
      if (open) open.style.opacity = String(position);
      if (closed) closed.style.opacity = String(1 - position);
    }
  }
}

const ERROR_CODE = "error_code";

type HassEntity = NonNullable<HomeAssistant["states"][string]>;
