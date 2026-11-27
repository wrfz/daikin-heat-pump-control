// node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: f, getOwnPropertySymbols: ee, getPrototypeOf: te } = Object, p = globalThis, ne = p.trustedTypes, re = ne ? ne.emptyScript : "", ie = p.reactiveElementPolyfillSupport, m = (e, t) => e, h = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? re : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, ae = (e, t) => !l(e, t), oe = {
	attribute: !0,
	type: String,
	converter: h,
	reflect: !1,
	useDefault: !1,
	hasChanged: ae
};
Symbol.metadata ??= Symbol("metadata"), p.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var g = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = oe) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? oe;
	}
	static _$Ei() {
		if (this.hasOwnProperty(m("elementProperties"))) return;
		let e = te(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(m("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(m("properties"))) {
			let e = this.properties, t = [...f(e), ...ee(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? h : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? h : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? ae)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
g.elementStyles = [], g.shadowRootOptions = { mode: "open" }, g[m("elementProperties")] = /* @__PURE__ */ new Map(), g[m("finalized")] = /* @__PURE__ */ new Map(), ie?.({ ReactiveElement: g }), (p.reactiveElementVersions ??= []).push("2.1.2");
// node_modules/lit-html/lit-html.js
var se = globalThis, ce = (e) => e, _ = se.trustedTypes, le = _ ? _.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, ue = "$lit$", v = `lit$${Math.random().toFixed(9).slice(2)}$`, de = "?" + v, fe = `<${de}>`, y = document, b = () => y.createComment(""), x = (e) => e === null || typeof e != "object" && typeof e != "function", pe = Array.isArray, me = (e) => pe(e) || typeof e?.[Symbol.iterator] == "function", he = "[ 	\n\f\r]", S = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, ge = /-->/g, _e = />/g, C = RegExp(`>|${he}(?:([^\\s"'>=/]+)(${he}*=${he}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), ve = /'/g, ye = /"/g, be = /^(?:script|style|textarea|title)$/i, w = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), T = Symbol.for("lit-noChange"), E = Symbol.for("lit-nothing"), xe = /* @__PURE__ */ new WeakMap(), D = y.createTreeWalker(y, 129);
function Se(e, t) {
	if (!pe(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return le === void 0 ? t : le.createHTML(t);
}
var Ce = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = S;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === S ? c[1] === "!--" ? o = ge : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = C) : (be.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = C) : o = _e : o === C ? c[0] === ">" ? (o = i ?? S, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? C : c[3] === "\"" ? ye : ve) : o === ye || o === ve ? o = C : o === ge || o === _e ? o = S : (o = C, i = void 0);
		let d = o === C && e[t + 1].startsWith("/>") ? " " : "";
		a += o === S ? n + fe : l >= 0 ? (r.push(s), n.slice(0, l) + ue + n.slice(l) + v + d) : n + v + (l === -2 ? t : d);
	}
	return [Se(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, O = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = Ce(t, n);
		if (this.el = e.createElement(l, r), D.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = D.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(ue)) {
					let t = u[o++], n = i.getAttribute(e).split(v), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? Te : r[1] === "?" ? Ee : r[1] === "@" ? De : j
					}), i.removeAttribute(e);
				} else e.startsWith(v) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (be.test(i.tagName)) {
					let e = i.textContent.split(v), t = e.length - 1;
					if (t > 0) {
						i.textContent = _ ? _.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], b()), D.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], b());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === de) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(v, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += v.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = y.createElement("template");
		return n.innerHTML = e, n;
	}
};
function k(e, t, n = e, r) {
	if (t === T) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = x(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = k(e, i._$AS(e, t.values), i, r)), t;
}
var we = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? y).importNode(t, !0);
		D.currentNode = r;
		let i = D.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new A(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new Oe(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = D.nextNode(), a++);
		}
		return D.currentNode = y, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, A = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = E, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = k(this, e, t), x(e) ? e === E || e == null || e === "" ? (this._$AH !== E && this._$AR(), this._$AH = E) : e !== this._$AH && e !== T && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? me(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== E && x(this._$AH) ? this._$AA.nextSibling.data = e : this.T(y.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = O.createElement(Se(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new we(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = xe.get(e.strings);
		return t === void 0 && xe.set(e.strings, t = new O(e)), t;
	}
	k(t) {
		pe(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(b()), this.O(b()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = ce(e).nextSibling;
			ce(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, j = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = E, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = E;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = k(this, e, t, 0), a = !x(e) || e !== this._$AH && e !== T, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = k(this, r[n + o], t, o), s === T && (s = this._$AH[o]), a ||= !x(s) || s !== this._$AH[o], s === E ? e = E : e !== E && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === E ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, Te = class extends j {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === E ? void 0 : e;
	}
}, Ee = class extends j {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== E);
	}
}, De = class extends j {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = k(this, e, t, 0) ?? E) === T) return;
		let n = this._$AH, r = e === E && n !== E || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== E && (n === E || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, Oe = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		k(this, e);
	}
};
(0, se.litHtmlPolyfillSupport)?.(O, A), (se.litHtmlVersions ??= []).push("3.3.3");
var ke = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new A(t.insertBefore(b(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, Ae = globalThis, M = class extends g {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = ke(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return T;
	}
};
M._$litElement$ = !0, M.finalized = !0, Ae.litElementHydrateSupport?.({ LitElement: M }), (0, Ae.litElementPolyfillSupport)?.({ LitElement: M }), (Ae.litElementVersions ??= []).push("4.2.2");
// node_modules/@lit/reactive-element/decorators/property.js
var je = {
	attribute: !0,
	type: String,
	converter: h,
	reflect: !1,
	hasChanged: ae
}, Me = (e = je, t, n) => {
	let { kind: r, metadata: i } = n, a = globalThis.litPropertyMetadata.get(i);
	if (a === void 0 && globalThis.litPropertyMetadata.set(i, a = /* @__PURE__ */ new Map()), r === "setter" && ((e = Object.create(e)).wrapped = !0), a.set(n.name, e), r === "accessor") {
		let { name: r } = n;
		return {
			set(n) {
				let i = t.get.call(this);
				t.set.call(this, n), this.requestUpdate(r, i, e, !0, n);
			},
			init(t) {
				return t !== void 0 && this.C(r, void 0, e, t), t;
			}
		};
	}
	if (r === "setter") {
		let { name: r } = n;
		return function(n) {
			let i = this[r];
			t.call(this, n), this.requestUpdate(r, i, e, !0, n);
		};
	}
	throw Error("Unsupported decorator location: " + r);
};
function N(e) {
	return (t, n) => typeof n == "object" ? Me(e, t, n) : ((e, t, n) => {
		let r = t.hasOwnProperty(n);
		return t.constructor.createProperty(n, e), r ? Object.getOwnPropertyDescriptor(t, n) : void 0;
	})(e, t, n);
}
// node_modules/@lit/reactive-element/decorators/state.js
function P(e) {
	return N({
		...e,
		state: !0,
		attribute: !1
	});
}
// node_modules/@lit/reactive-element/decorators/base.js
var Ne = (e, t, n) => (n.configurable = !0, n.enumerable = !0, Reflect.decorate && typeof t != "object" && Object.defineProperty(e, t, n), n);
// node_modules/@lit/reactive-element/decorators/query.js
function Pe(e, t) {
	return (n, r, i) => {
		let a = (t) => t.renderRoot?.querySelector(e) ?? null;
		if (t) {
			let { get: e, set: t } = typeof r == "object" ? n : i ?? (() => {
				let e = Symbol();
				return {
					get() {
						return this[e];
					},
					set(t) {
						this[e] = t;
					}
				};
			})();
			return Ne(n, r, { get() {
				let n = e.call(this);
				return n === void 0 && (n = a(this), (n !== null || this.hasUpdated) && t.call(this, n)), n;
			} });
		}
		return Ne(n, r, { get() {
			return a(this);
		} });
	};
}
// src/appearance.ts
var Fe = [
	"auto",
	"light",
	"dark",
	"petrol"
];
function Ie(e, t) {
	return `daikin_glass_${e === void 0 || e === "auto" ? t ? "dark" : "light" : e}.svg`;
}
var Le = (e) => Math.min(100, Math.max(0, Number(e)));
function Re(e) {
	if (!e) return;
	let t = e.trim().match(/^#([0-9a-f]{3,8})$/i);
	if (t?.[1]) {
		let e = t[1];
		(e.length === 3 || e.length === 4) && (e = [...e].map((e) => e + e).join(""));
		let n = parseInt(e.slice(0, 6), 16), r = e.length === 8 ? parseInt(e.slice(6, 8), 16) / 255 : 1;
		return [
			n >> 16 & 255,
			n >> 8 & 255,
			n & 255,
			r
		];
	}
	let n = e.match(/rgba?\(([^)]+)\)/);
	if (n?.[1]) {
		let [e = 0, t = 0, r = 0, i = 1] = n[1].split(",").map(parseFloat);
		return [
			e,
			t,
			r,
			i
		];
	}
}
function F(e, t, n) {
	if (e === void 0 && t === void 0) return;
	let r = Re(n), i = e ?? r?.slice(0, 3);
	if (!i) return;
	let a = t === void 0 ? e ? 1 : r?.[3] ?? 1 : Le(t) / 100, [o, s, c] = i;
	return a >= 1 ? `rgb(${o},${s},${c})` : `rgba(${o},${s},${c},${a})`;
}
var I = (e) => Array.isArray(e) && e.length === 3 && e.every((e) => Number.isInteger(e) && e >= 0 && e <= 255), ze = (e) => typeof e == "number" && e >= 0 && e <= 100, Be = {
	background: {
		show: (e) => typeof e == "boolean",
		color: I,
		opacity: ze
	},
	box: {
		fill: I,
		fill_opacity: ze,
		border: I,
		border_opacity: ze
	},
	text: {
		value_color: I,
		label_color: I
	}
};
function Ve(e) {
	for (let [t, n] of Object.entries(e)) {
		if (t === "type" || t === "grid_options" || t === "view_layout") continue;
		if (t === "layout") {
			if (!Fe.includes(n)) throw Error(`Invalid layout: ${String(n)}`);
			continue;
		}
		if (t === "animations") {
			if (typeof n != "boolean") throw Error(`Invalid option: ${t}`);
			continue;
		}
		let e = Be[t];
		if (!e) throw Error(`Unknown option: ${t}`);
		if (typeof n != "object" || !n || Array.isArray(n)) throw Error(`Invalid option: ${t}`);
		for (let [r, i] of Object.entries(n)) {
			let n = e[r];
			if (!n) throw Error(`Unknown option: ${t}.${r}`);
			if (!n(i)) throw Error(`Invalid option: ${t}.${r}`);
		}
	}
	return e;
}
function He(e) {
	let t = {};
	for (let [n, r] of Object.entries(e)) if (r != null && r !== "" && (n !== "layout" || r !== "auto") && (n !== "animations" || r !== !0)) {
		if (n in Be && typeof r == "object") {
			let e = Object.fromEntries(Object.entries(r).filter(([e, t]) => t != null && t !== "" && (n !== "background" || e !== "show" || t !== !0)));
			Object.keys(e).length > 0 && (t[n] = e);
		} else t[n] = r;
	}
	return t;
}
// \0@oxc-project+runtime@0.160.0/helpers/esm/decorate.js
function L(e, t, n, r) {
	var i = arguments.length, a = i < 3 ? t : r === null ? r = Object.getOwnPropertyDescriptor(t, n) : r, o;
	if (typeof Reflect == "object" && typeof Reflect.decorate == "function") a = Reflect.decorate(e, t, n, r);
	else for (var s = e.length - 1; s >= 0; s--) (o = e[s]) && (a = (i < 3 ? o(a) : i > 3 ? o(t, n, a) : o(t, n)) || a);
	return i > 3 && a && Object.defineProperty(t, n, a), a;
}
// src/card.ts
var Ue = "daikin-heat-pump-card", We = "daikin-heat-pump-card-editor", Ge = class extends M {
	setConfig(e) {
		Ve(e), this.config = e;
	}
	static getConfigElement() {
		return document.createElement(We);
	}
	static getStubConfig() {
		return {};
	}
	getCardSize() {
		return 12;
	}
	getGridOptions() {
		return {
			columns: "full",
			min_columns: 6,
			rows: "auto"
		};
	}
	render() {
		return w`<ha-card>
      <daikin-heat-pump-view
        .hass=${this.hass}
        .appearance=${this.config ?? {}}
      ></daikin-heat-pump-view>
    </ha-card>`;
	}
	static {
		this.styles = o`
    ha-card {
      overflow: hidden;
    }
  `;
	}
};
L([N({ attribute: !1 })], Ge.prototype, "hass", void 0), L([P()], Ge.prototype, "config", void 0);
var Ke = {
	label: {
		temperature_outside: "TA",
		ta2: "TA2",
		expansion_valve: "EEV",
		liquid: "Kondensat",
		circulation_pump: "Umwälzpumpe",
		flow_rate: "Durchfluss",
		return_flow: "Rücklauf",
		evaporator: "Verdampfer",
		hot_gas: "Heißgas",
		condensing: "Kondensation",
		hot_gas_condenser: "Heißgas",
		spread: "Spreizung",
		flow: "Vorlauf",
		flow_setpoint: "Vorlauf-Soll",
		pressure: "Druck",
		flow_bh: "Vorlauf BH",
		fan: "Lüfter",
		compressor: "Verdichter",
		storage: "Speicher",
		storage_setpoint: "Soll",
		backup_heater: "Heizstab"
	},
	info: {
		error_code: "Fehlercode:",
		operating_mode: "Modus:",
		mode_of_operating: "Betriebsart:",
		thermal_power: "Therm. Leistung:",
		electric_power: "El. Leistung:",
		cop: "COP:",
		room_temperature: "Raum-Ist:",
		room_setpoint: "Raum-Soll:"
	},
	prefix: {
		subcooling: "UK",
		discharge_superheat: "ÜH"
	},
	state: {
		unavailable: "n. v.",
		not_loaded: "Daikin Heat Pump Control ist nicht eingerichtet oder nicht geladen.",
		load_error: "Das Dashboard konnte nicht geladen werden."
	},
	editor: {
		layout: "Layout",
		layout_auto: "Automatisch (Dark-Mode)",
		layout_light: "Glas, hell",
		layout_dark: "Glas, dunkel",
		layout_petrol: "Glas, Petrol",
		animations: "Animationen",
		background: "Hintergrund",
		show: "Hintergrund anzeigen",
		color: "Farbe",
		opacity: "Deckkraft",
		box: "Boxen",
		fill: "Füllung",
		fill_opacity: "Deckkraft Füllung",
		border: "Rahmen",
		border_opacity: "Deckkraft Rahmen",
		text: "Text",
		value_color: "Werte",
		label_color: "Beschriftungen",
		reset: "Auf das Layout zurücksetzen",
		hint: "Werte, externe Entities und die Info-Box werden in den Optionen der Integration eingestellt (Dashboard)."
	},
	panel: {
		title: "Wärmepumpe",
		settings: "Darstellung",
		save: "Speichern",
		cancel: "Abbrechen",
		save_error: "Die Darstellung konnte nicht gespeichert werden.",
		all_users: "Die Darstellung des Panels gilt für alle Nutzer."
	},
	card: {
		name: "Daikin Wärmepumpe",
		description: "Schema der Wärmepumpe mit allen Werten der Integration Daikin Heat Pump Control."
	},
	master: {
		listening: "Eine andere Home-Assistant-Instanz steuert die Wärmepumpe; diese zeigt nur die Werte an.",
		claim: "Master werden",
		claim_error: "Diese Instanz konnte nicht Master werden."
	}
}, qe = {
	label: {
		temperature_outside: "TA",
		ta2: "TA2",
		expansion_valve: "EEV",
		liquid: "Liquid",
		circulation_pump: "Circulation pump",
		flow_rate: "Flow rate",
		return_flow: "Return",
		evaporator: "Evaporator",
		hot_gas: "Hot gas",
		condensing: "Condensing",
		hot_gas_condenser: "Hot gas",
		spread: "Spread",
		flow: "Flow",
		flow_setpoint: "Setpoint",
		pressure: "Pressure",
		flow_bh: "Flow BH",
		fan: "Fan",
		compressor: "Compressor",
		storage: "Tank",
		storage_setpoint: "Setpoint",
		backup_heater: "Backup heater"
	},
	info: {
		error_code: "Error code:",
		operating_mode: "Mode:",
		mode_of_operating: "Operation:",
		thermal_power: "Thermal power:",
		electric_power: "Electric power:",
		cop: "COP:",
		room_temperature: "Room:",
		room_setpoint: "Room setpoint:"
	},
	prefix: {
		subcooling: "SC",
		discharge_superheat: "SH"
	},
	state: {
		unavailable: "N/A",
		not_loaded: "Daikin Heat Pump Control is not set up or not loaded.",
		load_error: "The dashboard could not be loaded."
	},
	editor: {
		layout: "Layout",
		layout_auto: "Automatic (dark mode)",
		layout_light: "Glass, light",
		layout_dark: "Glass, dark",
		layout_petrol: "Glass, petrol",
		animations: "Animations",
		background: "Background",
		show: "Show background",
		color: "Colour",
		opacity: "Opacity",
		box: "Boxes",
		fill: "Fill",
		fill_opacity: "Fill opacity",
		border: "Border",
		border_opacity: "Border opacity",
		text: "Text",
		value_color: "Values",
		label_color: "Labels",
		reset: "Reset to the layout",
		hint: "Values, external entities and the info box are set in the options of the integration (Dashboard)."
	},
	panel: {
		title: "Heat pump",
		settings: "Appearance",
		save: "Save",
		cancel: "Cancel",
		save_error: "The appearance could not be saved.",
		all_users: "The appearance of the panel applies to all users."
	},
	card: {
		name: "Daikin heat pump",
		description: "Schematic of the heat pump with all values of the Daikin Heat Pump Control integration."
	},
	master: {
		listening: "Another Home Assistant instance controls the heat pump; this one only shows the values.",
		claim: "Become master",
		claim_error: "This instance could not become the master."
	}
}, Je = {
	de: Ke,
	en: qe,
	fr: {
		label: {
			temperature_outside: "TA",
			ta2: "TA2",
			expansion_valve: "EEV",
			liquid: "Liquide",
			circulation_pump: "Circulateur",
			flow_rate: "Débit",
			return_flow: "Retour",
			evaporator: "Évaporateur",
			hot_gas: "Gaz chaud",
			condensing: "Condensation",
			hot_gas_condenser: "Gaz chaud",
			spread: "Écart",
			flow: "Départ",
			flow_setpoint: "Consigne",
			pressure: "Pression",
			flow_bh: "Départ BH",
			fan: "Ventilateur",
			compressor: "Compresseur",
			storage: "Ballon",
			storage_setpoint: "Consigne",
			backup_heater: "Appoint"
		},
		info: {
			error_code: "Code d'erreur :",
			operating_mode: "Mode :",
			mode_of_operating: "Fonctionnement :",
			thermal_power: "Puiss. thermique :",
			electric_power: "Puiss. électrique :",
			cop: "COP :",
			room_temperature: "Pièce :",
			room_setpoint: "Consigne pièce :"
		},
		prefix: {
			subcooling: "SR",
			discharge_superheat: "SC"
		},
		state: {
			unavailable: "N/D",
			not_loaded: "Daikin Heat Pump Control n'est pas configuré ou pas chargé.",
			load_error: "Le tableau de bord n'a pas pu être chargé."
		},
		editor: {
			layout: "Disposition",
			layout_auto: "Automatique (mode sombre)",
			layout_light: "Verre, clair",
			layout_dark: "Verre, sombre",
			layout_petrol: "Verre, pétrole",
			animations: "Animations",
			background: "Arrière-plan",
			show: "Afficher l'arrière-plan",
			color: "Couleur",
			opacity: "Opacité",
			box: "Cadres",
			fill: "Remplissage",
			fill_opacity: "Opacité du remplissage",
			border: "Bordure",
			border_opacity: "Opacité de la bordure",
			text: "Texte",
			value_color: "Valeurs",
			label_color: "Libellés",
			reset: "Revenir à la disposition",
			hint: "Les valeurs, les entités externes et l'encadré d'informations se règlent dans les options de l'intégration (Tableau de bord)."
		},
		panel: {
			title: "Pompe à chaleur",
			settings: "Apparence",
			save: "Enregistrer",
			cancel: "Annuler",
			save_error: "L'apparence n'a pas pu être enregistrée.",
			all_users: "L'apparence du panneau s'applique à tous les utilisateurs."
		},
		card: {
			name: "Pompe à chaleur Daikin",
			description: "Schéma de la pompe à chaleur avec toutes les valeurs de l'intégration Daikin Heat Pump Control."
		},
		master: {
			listening: "Une autre instance de Home Assistant pilote la pompe à chaleur ; celle-ci affiche seulement les valeurs.",
			claim: "Devenir maître",
			claim_error: "Cette instance n'a pas pu devenir maître."
		}
	},
	it: {
		label: {
			temperature_outside: "TA",
			ta2: "TA2",
			expansion_valve: "EEV",
			liquid: "Condensato",
			circulation_pump: "Pompa circ.",
			flow_rate: "Portata",
			return_flow: "Ritorno",
			evaporator: "Evaporatore",
			hot_gas: "Gas caldo",
			condensing: "Condensazione",
			hot_gas_condenser: "Gas caldo",
			spread: "ΔT",
			flow: "Mandata",
			flow_setpoint: "Impostata",
			pressure: "Pressione",
			flow_bh: "Mandata BH",
			fan: "Ventilatore",
			compressor: "Compressore",
			storage: "Serbatoio",
			storage_setpoint: "Impostata",
			backup_heater: "Resistenza"
		},
		info: {
			error_code: "Codice errore:",
			operating_mode: "Modalità:",
			mode_of_operating: "Funzionamento:",
			thermal_power: "Potenza termica:",
			electric_power: "Potenza elettrica:",
			cop: "COP:",
			room_temperature: "Ambiente:",
			room_setpoint: "Ambiente impostata:"
		},
		prefix: {
			subcooling: "SR",
			discharge_superheat: "SS"
		},
		state: {
			unavailable: "N/D",
			not_loaded: "Daikin Heat Pump Control non è configurato o non è caricato.",
			load_error: "Impossibile caricare la dashboard."
		},
		editor: {
			layout: "Layout",
			layout_auto: "Automatico (modalità scura)",
			layout_light: "Vetro, chiaro",
			layout_dark: "Vetro, scuro",
			layout_petrol: "Vetro, petrolio",
			animations: "Animazioni",
			background: "Sfondo",
			show: "Mostra sfondo",
			color: "Colore",
			opacity: "Opacità",
			box: "Riquadri",
			fill: "Riempimento",
			fill_opacity: "Opacità riempimento",
			border: "Bordo",
			border_opacity: "Opacità bordo",
			text: "Testo",
			value_color: "Valori",
			label_color: "Etichette",
			reset: "Ripristina il layout",
			hint: "Valori, entità esterne e riquadro informazioni si impostano nelle opzioni dell'integrazione (Dashboard)."
		},
		panel: {
			title: "Pompa di calore",
			settings: "Aspetto",
			save: "Salva",
			cancel: "Annulla",
			save_error: "Impossibile salvare l'aspetto.",
			all_users: "L'aspetto del pannello vale per tutti gli utenti."
		},
		card: {
			name: "Pompa di calore Daikin",
			description: "Schema della pompa di calore con tutti i valori dell'integrazione Daikin Heat Pump Control."
		},
		master: {
			listening: "Un'altra istanza di Home Assistant controlla la pompa di calore; questa mostra solo i valori.",
			claim: "Diventa master",
			claim_error: "Questa istanza non è potuta diventare master."
		}
	}
};
function R(e) {
	let t = (e ?? "").split("-")[0]?.toLowerCase() ?? "";
	return t in Je ? t : "en";
}
function z(e, t) {
	let [n, r] = t.split(".", 2), i = (e) => e[n]?.[r];
	return i(Je[R(e)] ?? qe) ?? i(qe) ?? t;
}
// src/editor.ts
var Ye = { number: {
	min: 0,
	max: 100,
	step: 1,
	mode: "slider",
	unit_of_measurement: "%"
} }, B = { color_rgb: {} };
function Xe(e) {
	let t = (t) => z(e, `editor.${t}`);
	return [
		{
			name: "layout",
			selector: { select: {
				mode: "dropdown",
				options: Fe.map((e) => ({
					value: e,
					label: t(`layout_${e}`)
				}))
			} }
		},
		{
			name: "animations",
			selector: { boolean: {} }
		},
		{
			name: "background",
			type: "expandable",
			title: t("background"),
			schema: [
				{
					name: "show",
					selector: { boolean: {} }
				},
				{
					name: "color",
					selector: B
				},
				{
					name: "opacity",
					selector: Ye
				}
			]
		},
		{
			name: "box",
			type: "expandable",
			title: t("box"),
			schema: [
				{
					name: "fill",
					selector: B
				},
				{
					name: "fill_opacity",
					selector: Ye
				},
				{
					name: "border",
					selector: B
				},
				{
					name: "border_opacity",
					selector: Ye
				}
			]
		},
		{
			name: "text",
			type: "expandable",
			title: t("text"),
			schema: [{
				name: "value_color",
				selector: B
			}, {
				name: "label_color",
				selector: B
			}]
		}
	];
}
function Ze(e) {
	return {
		...e,
		layout: e.layout ?? "auto",
		animations: e.animations !== !1,
		background: {
			show: !0,
			...e.background
		}
	};
}
async function Qe() {
	customElements.get("ha-form") || await ((await window.loadCardHelpers?.())?.createCardElement({
		type: "entities",
		entities: []
	}))?.constructor.getConfigElement?.();
}
var V = class extends M {
	constructor(...e) {
		super(...e), this.config = {}, this.formReady = !1;
	}
	setConfig(e) {
		this.config = e;
	}
	connectedCallback() {
		super.connectedCallback(), Qe().then(() => this.formReady = !0);
	}
	get language() {
		return R(this.hass?.locale?.language ?? this.hass?.language);
	}
	render() {
		let e = this.language;
		return w`
      ${this.formReady ? w`<ha-form
              .hass=${this.hass}
              .data=${Ze(this.config)}
              .schema=${Xe(e)}
              .computeLabel=${(t) => z(e, `editor.${t.name}`)}
              @value-changed=${this.valueChanged}
            ></ha-form>` : ""}
      <div class="actions">
        <button type="button" @click=${this.reset}>
          ${z(e, "editor.reset")}
        </button>
      </div>
      <p class="hint">${z(e, "editor.hint")}</p>
    `;
	}
	valueChanged(e) {
		e.stopPropagation(), this.changed({
			...this.config,
			...e.detail.value
		});
	}
	reset() {
		let e = this.config.type;
		this.changed(e === void 0 ? {} : { type: e });
	}
	changed(e) {
		this.config = He(e), this.dispatchEvent(new CustomEvent("config-changed", {
			detail: { config: this.config },
			bubbles: !0,
			composed: !0
		}));
	}
	static {
		this.styles = o`
    .actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 12px;
    }
    button {
      font: inherit;
      color: var(--primary-color);
      background: none;
      border: 1px solid var(--divider-color);
      border-radius: 18px;
      padding: 6px 14px;
      cursor: pointer;
    }
    .hint {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
  `;
	}
};
L([N({ attribute: !1 })], V.prototype, "hass", void 0), L([N({ attribute: !1 })], V.prototype, "config", void 0), L([P()], V.prototype, "formReady", void 0);
// src/format.ts
var $e = /* @__PURE__ */ new Set([
	"sensor",
	"number",
	"input_number"
]), et = (e) => e === "unknown" || e === "unavailable";
function tt(e) {
	if (!e || et(e.state) || e.state.trim() === "") return;
	let t = Number(e.state);
	return Number.isFinite(t) ? t : void 0;
}
function nt(e, t, n) {
	let r = e.locale?.language ?? e.language;
	if (et(t.state)) return n.dashUnknown ? {
		text: "---",
		state: "normal"
	} : {
		text: z(r, "state.unavailable"),
		state: "unavailable"
	};
	let i = t.entity_id.split(".")[0] ?? "", a = tt(t);
	if (a !== void 0 && $e.has(i)) {
		let e = new Intl.NumberFormat(r, {
			minimumFractionDigits: n.digits,
			maximumFractionDigits: n.digits
		}).format(a), i = t.attributes.unit_of_measurement;
		return {
			text: typeof i == "string" && i ? `${e} ${i}` : e,
			state: "normal"
		};
	}
	return {
		text: e.formatEntityState?.(t) ?? t.state,
		state: "normal"
	};
}
function rt(e) {
	return e.search(/[,.]\d/);
}
// src/matrix.ts
var it = [
	1,
	0,
	0,
	1,
	0,
	0
];
function H(e, t) {
	return [
		e[0] * t[0] + e[2] * t[1],
		e[1] * t[0] + e[3] * t[1],
		e[0] * t[2] + e[2] * t[3],
		e[1] * t[2] + e[3] * t[3],
		e[0] * t[4] + e[2] * t[5] + e[4],
		e[1] * t[4] + e[3] * t[5] + e[5]
	];
}
function at(e) {
	let t = e[0] * e[3] - e[1] * e[2];
	return [
		e[3] / t,
		-e[1] / t,
		-e[2] / t,
		e[0] / t,
		(e[2] * e[5] - e[3] * e[4]) / t,
		(e[1] * e[4] - e[0] * e[5]) / t
	];
}
function ot(e, t, n) {
	return [e[0] * t + e[2] * n + e[4], e[1] * t + e[3] * n + e[5]];
}
function st(e) {
	let t = it;
	if (!e) return t;
	for (let [, n, r] of e.matchAll(/(\w+)\s*\(([^)]*)\)/g)) {
		let e = (r ?? "").split(/[\s,]+/).filter((e) => e !== "").map(Number), i = it;
		switch (n) {
			case "translate":
				i = [
					1,
					0,
					0,
					1,
					e[0] ?? 0,
					e[1] ?? 0
				];
				break;
			case "scale":
				i = [
					e[0] ?? 1,
					0,
					0,
					e[1] ?? e[0] ?? 1,
					0,
					0
				];
				break;
			case "rotate": {
				let t = (e[0] ?? 0) * Math.PI / 180, n = Math.cos(t), r = Math.sin(t), [a = 0, o = 0] = [e[1], e[2]];
				i = H(H([
					1,
					0,
					0,
					1,
					a,
					o
				], [
					n,
					r,
					-r,
					n,
					0,
					0
				]), [
					1,
					0,
					0,
					1,
					-a,
					-o
				]);
				break;
			}
			case "matrix": e.length === 6 && (i = e);
		}
		t = H(t, i);
	}
	return t;
}
function ct(e, t) {
	let n = [];
	for (let r = e; r && r !== t;) n.unshift(r), r = r.parentElement;
	return n.reduce((e, t) => H(e, st(t.getAttribute("transform"))), it);
}
// src/values.ts
var U = { framed: !0 }, lt = [
	{
		id: "TA",
		...U
	},
	{
		id: "TA2",
		...U
	},
	{
		id: "EEV",
		...U
	},
	{
		id: "Kondensat",
		...U
	},
	{
		id: "Umwaelzpumpe",
		...U
	},
	{
		id: "Durchfluss",
		...U
	},
	{
		id: "Ruecklauf",
		...U
	},
	{
		id: "Verdampfer",
		...U
	},
	{
		id: "hot_gas",
		...U
	},
	{
		id: "Kondensation",
		...U
	},
	{
		id: "hot_gas_condenser",
		...U
	},
	{
		id: "Spreizung",
		...U
	},
	{
		id: "Vorlauf",
		...U
	},
	{
		id: "Vorlauf-Soll",
		...U
	},
	{
		id: "Druck",
		...U
	},
	{
		id: "Vorlauf-BH",
		...U
	},
	{
		id: "Luefter",
		...U
	},
	{
		id: "Verdichter",
		...U
	},
	{
		id: "Speicher",
		...U
	},
	{
		id: "Speicher-Soll",
		...U
	},
	{
		id: "buh",
		...U
	},
	{
		id: "DHW-Valve",
		fontSize: 40
	},
	{
		id: "BPV-Valve",
		fontSize: 40
	},
	{
		id: "Info",
		...U,
		fontSize: 40,
		alignLeft: !0,
		info: !0
	}
], W = { digits: 1 }, G = { digits: 0 }, K = {
	digits: 1,
	dashUnknown: !0
}, ut = {
	temperature_outside: W,
	ta2: W,
	expansion_valve: G,
	liquid_temperature: W,
	subcooling: {
		...K,
		prefix: !0
	},
	circulation_pump: G,
	flow_rate: G,
	tr: W,
	evaporator_temperature: W,
	hot_gas_temperature: W,
	discharge_superheat: {
		...K,
		prefix: !0
	},
	saturation_temperature: K,
	hot_gas_condenser: W,
	refrigerant_pressure: K,
	temperature_spread: W,
	tv: W,
	target_supply_temperature: W,
	water_pressure: W,
	tvbh: W,
	tv_uart: W,
	tr_uart: W,
	tvbh_uart: W,
	fan_speed: G,
	compressor_speed: G,
	hot_water_temperature: W,
	hot_water_setpoint: W,
	backup_heater_power: G,
	dhw_mixer_position: G,
	bypass_valve: G,
	error_code: W,
	operating_mode: W,
	mode_of_operating: W,
	thermal_power: W,
	electric_power: W,
	cop: W,
	room_temperature: W,
	room_setpoint: W
}, dt = "http://www.w3.org/2000/svg", ft = 8.75, q = (e, t) => parseFloat(e.getAttribute(t) ?? "0") || 0, J = (e, t = {}) => {
	let n = document.createElementNS(dt, e);
	for (let [e, r] of Object.entries(t)) n.setAttribute(e, r);
	return n;
}, Y = (e, t) => {
	e && (e.style.display = t ? "" : "none");
}, pt = (e, t) => {
	try {
		return JSON.parse(e.getAttribute(t) ?? "{}");
	} catch {
		return {};
	}
}, mt = (e) => (e.match(/-?[\d.]+/g) ?? []).map(Number), ht = class {
	constructor(e, t, n) {
		this.language = n, this.groups = [];
		let r = new DOMParser().parseFromString(e, "image/svg+xml").documentElement;
		if (r.tagName.toLowerCase() !== "svg") throw Error("Not an SVG layout");
		this.svg = document.importNode(r, !0), this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet"), this.svg.setAttribute("data-animations", t.animations === !1 ? "off" : "on"), this.style = this.layoutStyle(t), this.runMap = pt(this.svg, "data-run-map"), this.tempVars = pt(this.svg, "data-temp-vars");
		for (let e of lt) {
			let t = this.find(e.id);
			t && this.groups.push(this.buildGroup(e, t));
		}
	}
	find(e) {
		return this.svg.querySelector(`[id="${e}"]`);
	}
	layoutStyle(e) {
		let t = (e) => this.svg.getAttribute(e) ?? void 0, n = {
			radius: t("data-box-radius"),
			fill: t("data-box-fill"),
			stroke: t("data-box-stroke"),
			strokeWidth: t("data-box-stroke-width"),
			text: t("data-text-color"),
			label: t("data-label-color"),
			ownStates: this.svg.hasAttribute("data-own-state-style")
		}, { box: r, text: i, background: a } = e;
		if (n.fill = F(r?.fill, r?.fill_opacity, n.fill) ?? n.fill, n.stroke = F(r?.border, r?.border_opacity, n.stroke) ?? n.stroke, n.text = F(i?.value_color, void 0, void 0) ?? n.text, n.label = F(i?.label_color, void 0, void 0) ?? n.label, a?.show === !1) this.svg.setAttribute("data-bg", "off");
		else {
			let e = F(a?.color, void 0, void 0);
			if (e && this.svg.style.setProperty("--bg-color", e), a?.opacity !== void 0) {
				let e = Math.min(100, Math.max(0, a.opacity)) / 100;
				this.svg.style.setProperty("--bg-opacity", String(e));
			}
		}
		return n;
	}
	boxStyle(e, t) {
		e.setAttribute("fill", t), e.setAttribute("stroke", this.style.stroke ?? "#000000"), e.setAttribute("stroke-width", this.style.strokeWidth ?? "2px"), this.style.radius !== void 0 && (e.setAttribute("rx", this.style.radius), e.setAttribute("ry", this.style.radius));
	}
	buildGroup(e, t) {
		let n = [...t.querySelectorAll("rect")], r = t.querySelector("rect[data-label]"), i = n.filter((e) => e.hasAttribute("data-value") || /_val(ue)?$/.test(e.id)).sort((e, t) => q(e, "y") - q(t, "y")), a = Math.min(...n.map((e) => q(e, "y"))), o = parseFloat(this.style.radius ?? "0") > 0, s = this.style.fill ?? "none", c = {
			spec: e,
			element: t,
			top: a,
			slots: i.map((e) => q(e, "y")),
			rows: [],
			hasLabel: r !== null,
			leaders: [...this.svg.querySelectorAll(`path[data-box="${e.id}"]`)],
			bottomLeaders: []
		}, l = parseFloat(t.getAttribute("data-sep") ?? "");
		if (Number.isFinite(l) && (c.separator = l), e.framed && o) {
			let r = Math.min(...n.map((e) => q(e, "x"))), i = Math.max(...n.map((e) => q(e, "x") + q(e, "width"))), o = Math.max(...n.map((e) => q(e, "y") + q(e, "height"))), l = J("rect", {
				id: `${e.id}_rect`,
				x: String(r),
				y: String(a),
				width: String(i - r),
				height: String(o - a)
			});
			this.boxStyle(l, s), t.insertBefore(l, t.firstChild), c.frame = l;
		}
		if (r) {
			let e = this.createText(r, 35);
			e.setAttribute("fill", this.style.label ?? "#808080"), e.setAttribute("x", String(q(r, "x") + q(r, "width") / 2)), e.setAttribute("y", String(q(r, "y") + q(r, "height") / 2 + 3)), e.setAttribute("text-anchor", "middle"), e.textContent = z(this.language, `label.${r.getAttribute("data-label") ?? ""}`), t.appendChild(e), c.frame ? r.remove() : this.boxStyle(r, s);
		}
		return i.forEach((n, i) => {
			let a = {
				value: n.getAttribute("data-value"),
				rect: n,
				height: q(n, "height")
			};
			e.framed && (c.frame ? (n.setAttribute("fill", "none"), n.setAttribute("stroke", "none"), (r || e.info || i > 0) && (a.divider = J("line", {
				x1: String(q(n, "x")),
				x2: String(q(n, "x") + q(n, "width")),
				stroke: this.style.stroke ?? "#000000",
				"stroke-width": "1.5",
				"stroke-opacity": "0.6"
			}), t.appendChild(a.divider))) : this.boxStyle(n, s)), a.value && (a.text = this.createText(n, e.fontSize ?? 56), a.text.id = `${n.id}_text`, t.appendChild(a.text)), c.rows.push(a);
		}), c.bottomLeaders = this.bottomLeaders(c), c;
	}
	bottomLeaders(e) {
		let t = [...e.element.querySelectorAll("path[data-edge=\"bottom\"]")], n = e.leaders.filter((e) => e.getAttribute("data-edge") === "bottom"), r = ct(e.element, this.svg);
		return [...t, ...n].map((e) => {
			let [n = 0, i = 0, a = 0, o = 0] = mt(e.getAttribute("d") ?? ""), s = t.includes(e) ? [
				1,
				0,
				0,
				1,
				0,
				0
			] : H(at(ct(e, this.svg)), r);
			return {
				path: e,
				start: ot(at(s), n, i),
				end: `${a} ${o}`,
				toPath: s
			};
		});
	}
	createText(e, t) {
		let n = J("text", {
			"dominant-baseline": "middle",
			"stroke-width": "1",
			"font-size": String(t)
		}), r = e.getAttribute("transform");
		return r && n.setAttribute("transform", r), n;
	}
	update(e, t) {
		let n = (e) => t.entities[e], r = (t) => {
			let r = n(t);
			return r ? e.states[r] : void 0;
		};
		for (let n of this.groups) this.updateGroup(n, e, t, r);
		this.updateRunMap(r), this.updateTempVars(r), this.updateValves(r);
		for (let t of this.svg.querySelectorAll("[data-more-info]")) {
			let r = n(t.getAttribute("data-more-info") ?? "");
			r && e.states[r] ? (t.setAttribute("data-entity", r), t.setAttribute("cursor", "pointer")) : (t.removeAttribute("data-entity"), t.removeAttribute("cursor"));
		}
	}
	updateGroup(e, t, n, r) {
		let i = [];
		for (let t of e.rows) {
			let e = t.value === null ? void 0 : r(t.value);
			t.value !== null && e && i.push({
				row: t,
				value: t.value,
				entity: e
			});
		}
		if (e.spec.info) {
			let e = n.info;
			i = i.filter((t) => e.includes(t.value)).sort((t, n) => e.indexOf(t.value) - e.indexOf(n.value));
		}
		Y(e.element, i.length > 0);
		for (let t of e.leaders) Y(t, i.length > 0);
		for (let t of e.rows) {
			let e = i.some((e) => e.row === t);
			Y(t.rect, e), Y(t.text, e), Y(t.divider, e);
		}
		if (i.length === 0) return;
		let a = e.top;
		if (i.forEach(({ row: n, value: r, entity: i }, o) => {
			let s = e.slots[o] ?? q(n.rect, "y");
			n.rect.setAttribute("y", String(s)), n.divider && (n.divider.setAttribute("y1", String(s)), n.divider.setAttribute("y2", String(s)), Y(n.divider, o > 0 || e.hasLabel)), n.text && this.updateText(e, n, n.text, r, s, t, i), a = s + n.height;
		}), e.frame) {
			e.frame.setAttribute("height", String(a - e.top));
			for (let t of e.bottomLeaders) {
				let [e, n] = ot(t.toPath, t.start[0], a);
				t.path.setAttribute("d", `M${e.toFixed(2)} ${n.toFixed(2)} L${t.end}`);
			}
		}
	}
	updateText(e, t, n, r, i, a, o) {
		let s = ut[r] ?? { digits: 1 }, c = nt(a, o, s), l = c.state;
		r === gt && l === "normal" && o.state !== "no_error" && (l = "error");
		let u = e.spec.info ? `${z(this.language, `info.${r}`)} ${c.text}` : c.text, d = s.prefix ? z(this.language, `prefix.${r}`) : void 0;
		this.setText(n, u, d, l === "normal" ? e.separator : void 0);
		let f = t.rect, ee = e.spec.alignLeft || f.getAttribute("data-align") === "left";
		n.setAttribute("x", String(ee ? q(f, "x") : q(f, "x") + q(f, "width") / 2)), n.setAttribute("text-anchor", ee ? "start" : "middle"), n.setAttribute("y", String(i + t.height / 2 + (e.spec.offset ?? 6))), n.setAttribute("data-entity", o.entity_id), n.setAttribute("cursor", "pointer"), n.setAttribute("data-state", l), l === "normal" || !this.style.ownStates ? n.setAttribute("fill", l === "normal" ? this.style.text ?? "currentColor" : l === "error" ? "red" : "orange") : n.removeAttribute("fill");
	}
	setText(e, t, n, r) {
		let i = r === void 0 ? -1 : rt(t);
		if (e.textContent = "", !n && i < 0) {
			e.textContent = t;
			return;
		}
		let a = (e, t, n = {}) => {
			let r = J("tspan", n);
			return r.textContent = t, e.appendChild(r), r;
		}, o = i >= 0 ? a(e, "", {
			x: String(r),
			"text-anchor": "end"
		}) : e;
		n && a(o, n, {
			"font-size": "35",
			fill: this.style.label ?? "#808080"
		}), a(o, i >= 0 ? t.slice(0, i) : t, n ? { dx: String(3 * ft) } : {}), i >= 0 && a(e, t.slice(i), {
			x: String(r),
			"text-anchor": "start"
		});
	}
	updateRunMap(e) {
		for (let [t, n] of Object.entries(this.runMap)) {
			let r = this.find(t);
			if (!r) continue;
			let i = e(n.id)?.state, a = "unknown";
			if (i !== void 0 && i !== "unknown" && i !== "unavailable") {
				let e = Array.isArray(n.value) ? n.value : [n.value];
				a = (n.mode === "gt0" ? parseFloat(i) > 0 : n.mode === "eq" ? e.includes(i) : i === "on") ? "on" : "off";
			}
			r.setAttribute("data-state", a);
		}
	}
	updateTempVars(e) {
		for (let [t, n] of Object.entries(this.tempVars)) {
			let r = (Array.isArray(n.id) ? n.id : [n.id]).map((t) => tt(e(t))).find((e) => e !== void 0);
			if (r !== void 0 && n.max !== n.min) {
				let e = Math.min(1, Math.max(0, (r - n.min) / (n.max - n.min)));
				this.svg.style.setProperty(t, e.toFixed(3));
			} else this.svg.style.removeProperty(t);
		}
	}
	updateValves(e) {
		let t = (t) => Math.min(1, Math.max(0, (tt(e(t)) ?? 0) / 100));
		for (let [e, n, r, i] of [[
			"dhw-flap",
			"dhw-open-arrows",
			"dhw-closed-arrows",
			"dhw_mixer_position"
		], [
			"bpv-flap",
			"bpv-open-arrows",
			"bpv-closed-arrows",
			"bypass_valve"
		]]) {
			let a = t(i), o = this.find(e);
			if (o) {
				let [e = "0", t = "0"] = (o.getAttribute("data-pivot") ?? "0 0").split(" "), n = q(o, "data-a0"), r = q(o, "data-a1");
				o.setAttribute("transform", `rotate(${n + (r - n) * a} ${e} ${t})`);
			}
			let s = this.find(n), c = this.find(r);
			s && (s.style.opacity = String(a)), c && (c.style.opacity = String(1 - a));
		}
	}
}, gt = "error_code", X = "daikin_heat_pump_control", _t = /* @__PURE__ */ new Map();
function vt(e, t = import.meta.url) {
	let n = new URL(e, t);
	return n.search = new URL(t).search, n.href;
}
function yt(e) {
	let t = _t.get(e);
	return t || (t = fetch(vt(e)).then((t) => {
		if (!t.ok) throw Error(`${e}: ${t.status}`);
		return t.text();
	}), t.catch(() => _t.delete(e)), _t.set(e, t)), t;
}
var bt = 500, Z = class extends M {
	constructor(...e) {
		super(...e), this.appearance = {}, this.claimError = !1;
	}
	connectedCallback() {
		super.connectedCallback(), this.hass && this.subscribe();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), clearTimeout(this.refreshTimer), this.unsubscribe?.then((e) => e?.()), this.unsubscribe = void 0, this.unsubscribeMaster?.then((e) => e?.()), this.unsubscribeMaster = void 0;
	}
	get language() {
		return R(this.hass?.locale?.language ?? this.hass?.language);
	}
	get file() {
		return Ie(this.appearance.layout, this.hass?.themes?.darkMode ?? !1);
	}
	subscribe() {
		!this.unsubscribe && this.hass && (this.fetchData(), this.unsubscribe = this.hass.connection.subscribeEvents(() => {
			clearTimeout(this.refreshTimer), this.refreshTimer = setTimeout(() => void this.fetchData(), bt);
		}, "entity_registry_updated").catch(() => void 0), this.unsubscribeMaster = this.hass.connection.subscribeMessage((e) => {
			this.master = e;
		}, { type: `${X}/master/subscribe` }).catch(() => void 0));
	}
	get listening() {
		return this.master !== void 0 && !this.master.master && this.master.clients > 1;
	}
	async claim() {
		if (this.hass) try {
			await this.hass.callWS({ type: `${X}/master/claim` }), this.claimError = !1;
		} catch {
			this.claimError = !0;
		}
	}
	async fetchData() {
		if (this.hass) try {
			this.data = await this.hass.callWS({ type: `${X}/entities` }), this.error = void 0;
		} catch (e) {
			let t = e?.code;
			this.error = t === "not_loaded" ? "state.not_loaded" : "state.load_error";
		}
	}
	willUpdate(e) {
		e.has("hass") && this.hass && this.isConnected && this.subscribe();
		let t = this.file;
		this.source?.file !== t && this.loading !== t && (this.loading = t, yt(t).then((e) => {
			this.loading === t && (this.source = {
				file: t,
				text: e
			});
		}, () => {
			this.loading === t && (this.error = "state.load_error");
		}));
	}
	render() {
		if (this.error) return w`<div class="message">
        ${z(this.language, this.error)}
      </div>`;
		let e = (e) => z(this.language, e);
		return w`${this.listening ? w`<div class="master">
              <span>${e("master.listening")}</span>
              ${this.hass?.user?.is_admin ? w`<button type="button" @click=${this.claim}>
                      ${e("master.claim")}
                    </button>` : ""}
              ${this.claimError ? w`<span class="error">${e("master.claim_error")}</span>` : ""}
            </div>` : ""}
      <div class="schema" @click=${this.onClick}></div>`;
	}
	updated() {
		let e = this.renderRoot.querySelector(".schema");
		if (!e || !this.source || !this.hass || !this.data) return;
		let t = JSON.stringify([
			this.source.file,
			this.appearance,
			this.language
		]);
		this.schema && this.schemaKey === t || (this.schema = new ht(this.source.text, this.appearance, this.language), this.schemaKey = t, e.replaceChildren(this.schema.svg)), this.schema.update(this.hass, this.data);
	}
	onClick(e) {
		let t = (e.target?.closest?.("[data-entity]"))?.getAttribute("data-entity");
		t && this.dispatchEvent(new CustomEvent("hass-more-info", {
			detail: { entityId: t },
			bubbles: !0,
			composed: !0
		}));
	}
	static {
		this.styles = o`
    :host {
      display: block;
    }
    .schema svg {
      display: block;
      width: 100%;
      height: auto;
    }
    :host([fit]) .schema svg {
      height: var(--daikin-view-height, auto);
      max-height: var(--daikin-view-height, none);
    }
    .message {
      padding: 16px;
      color: var(--secondary-text-color);
    }
    .master {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 16px;
      padding: 8px 16px;
      margin-bottom: 8px;
      border-radius: var(--ha-card-border-radius, 12px);
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .master span {
      flex: 1;
    }
    .master .error {
      flex-basis: 100%;
    }
    .master button {
      font: inherit;
      padding: 6px 14px;
      border-radius: 18px;
      border: 1px solid currentColor;
      background: none;
      color: inherit;
      cursor: pointer;
    }
  `;
	}
};
L([N({ attribute: !1 })], Z.prototype, "hass", void 0), L([N({ attribute: !1 })], Z.prototype, "appearance", void 0), L([P()], Z.prototype, "data", void 0), L([P()], Z.prototype, "error", void 0), L([P()], Z.prototype, "source", void 0), L([P()], Z.prototype, "master", void 0), L([P()], Z.prototype, "claimError", void 0);
// src/panel.ts
var xt = "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z", Q = class extends M {
	constructor(...e) {
		super(...e), this.narrow = !1, this.appearance = {}, this.saveError = !1, this.loaded = !1;
	}
	get language() {
		return R(this.hass?.locale?.language ?? this.hass?.language);
	}
	willUpdate(e) {
		e.has("hass") && this.hass && !this.loaded && (this.loaded = !0, this.loadAppearance());
	}
	async loadAppearance() {
		if (this.hass) try {
			let e = await this.hass.callWS({ type: `${X}/panel_config` });
			this.appearance = e.config;
		} catch {}
	}
	render() {
		let e = (e) => z(this.language, e);
		return w`
      <div class="toolbar">
        <ha-menu-button
          .hass=${this.hass}
          .narrow=${this.narrow}
        ></ha-menu-button>
        <div class="title">${e("panel.title")}</div>
        ${this.hass?.user?.is_admin ? w`<ha-icon-button
                .path=${xt}
                .label=${e("panel.settings")}
                @click=${this.openSettings}
              ></ha-icon-button>` : ""}
      </div>
      <div class="content">
        <daikin-heat-pump-view
          fit
          .hass=${this.hass}
          .appearance=${this.draft ?? this.appearance}
        ></daikin-heat-pump-view>
      </div>
      <dialog @close=${this.closed}>
        <h2>${e("panel.settings")}</h2>
        <p class="note">${e("panel.all_users")}</p>
        ${this.draft === void 0 ? "" : w`<daikin-heat-pump-card-editor
                .hass=${this.hass}
                .config=${this.draft}
                @config-changed=${this.draftChanged}
              ></daikin-heat-pump-card-editor>`}
        ${this.saveError ? w`<p class="error">${e("panel.save_error")}</p>` : ""}
        <div class="buttons">
          <button type="button" @click=${this.cancel}>
            ${e("panel.cancel")}
          </button>
          <button type="button" class="primary" @click=${this.save}>
            ${e("panel.save")}
          </button>
        </div>
      </dialog>
    `;
	}
	async openSettings() {
		this.draft = { ...this.appearance }, this.saveError = !1, await this.updateComplete, this.dialog?.showModal();
	}
	draftChanged(e) {
		this.draft = e.detail.config;
	}
	cancel() {
		this.dialog?.close();
	}
	closed() {
		this.draft = void 0;
	}
	async save() {
		if (this.hass) try {
			let e = await this.hass.callWS({
				type: `${X}/panel_config/set`,
				config: this.draft ?? {}
			});
			this.appearance = e.config, this.dialog?.close();
		} catch {
			this.saveError = !0;
		}
	}
	static {
		this.styles = o`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      --daikin-view-height: calc(100vh - var(--header-height, 56px) - 32px);
    }
    .toolbar {
      display: flex;
      align-items: center;
      height: var(--header-height, 56px);
      padding: 0 12px;
      box-sizing: border-box;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, var(--text-primary-color));
      border-bottom: var(--app-header-border-bottom, none);
    }
    .title {
      flex: 1;
      margin-left: 12px;
      font-size: 20px;
    }
    .content {
      padding: 16px;
    }
    dialog {
      width: min(560px, calc(100vw - 32px));
      max-height: calc(100vh - 64px);
      border: none;
      border-radius: var(--ha-dialog-border-radius, 24px);
      background: var(--card-background-color, var(--primary-background-color));
      color: var(--primary-text-color);
      padding: 24px;
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.4);
    }
    h2 {
      margin: 0 0 8px;
      font-size: 22px;
      font-weight: 400;
    }
    .note {
      margin: 0 0 16px;
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color);
    }
    .buttons {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 16px;
    }
    button {
      font: inherit;
      padding: 8px 16px;
      border-radius: 18px;
      border: 1px solid var(--divider-color);
      background: none;
      color: var(--primary-color);
      cursor: pointer;
    }
    button.primary {
      background: var(--primary-color);
      color: var(--text-primary-color);
      border-color: var(--primary-color);
    }
  `;
	}
};
L([N({ attribute: !1 })], Q.prototype, "hass", void 0), L([N({ type: Boolean })], Q.prototype, "narrow", void 0), L([P()], Q.prototype, "appearance", void 0), L([P()], Q.prototype, "draft", void 0), L([P()], Q.prototype, "saveError", void 0), L([Pe("dialog")], Q.prototype, "dialog", void 0);
// src/main.ts
var $ = (e, t) => {
	customElements.get(e) || customElements.define(e, t);
};
$("daikin-heat-pump-view", Z), $(Ue, Ge), $(We, V), $("daikin-heat-pump-panel", Q);
var St = window;
if (St.customCards ??= [], !St.customCards.some((e) => e.type === "daikin-heat-pump-card")) {
	let e = R(document.documentElement.lang || navigator.language);
	St.customCards.push({
		type: Ue,
		name: z(e, "card.name"),
		description: z(e, "card.description"),
		preview: !0,
		documentationURL: "https://github.com/wrfz/daikin-heat-pump-control"
	});
}
