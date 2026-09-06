import { parseAst } from "vite";
import MagicString from "magic-string";
//#region src/plugins/strip-server-exports.ts
/**
* Strip server-only data-fetching exports (getServerSideProps,
* getStaticProps, getStaticPaths) from page modules for the client
* bundle. Uses Vite's parseAst (Rollup/acorn) for correct handling
* of all export patterns including function expressions, arrow
* functions with TS return types, and re-exports.
*
* Modeled after Next.js's SWC `next-ssg-transform`.
*/
function stripServerExports(code) {
	const SERVER_EXPORTS = new Set([
		"getServerSideProps",
		"getStaticProps",
		"getStaticPaths"
	]);
	if (![...SERVER_EXPORTS].some((name) => code.includes(name))) return null;
	let ast;
	try {
		ast = parseAst(code);
	} catch {
		return null;
	}
	const s = new MagicString(code);
	let changed = false;
	for (const node of ast.body) {
		if (node.type !== "ExportNamedDeclaration") continue;
		if (node.declaration) {
			const decl = node.declaration;
			if (decl.type === "FunctionDeclaration" && decl.id && SERVER_EXPORTS.has(decl.id.name)) {
				s.overwrite(node.start, node.end, `export function ${decl.id.name}() { return { props: {} }; }`);
				changed = true;
			} else if (decl.type === "VariableDeclaration") {
				for (const declarator of decl.declarations) if (declarator.id?.type === "Identifier" && SERVER_EXPORTS.has(declarator.id.name)) {
					s.overwrite(node.start, node.end, `export const ${declarator.id.name} = undefined;`);
					changed = true;
				}
			}
			continue;
		}
		if (node.specifiers && node.specifiers.length > 0 && !node.source) {
			const kept = [];
			const stripped = [];
			for (const spec of node.specifiers) {
				const exportedName = spec.exported?.name ?? spec.exported?.value;
				if (SERVER_EXPORTS.has(exportedName)) stripped.push(exportedName);
				else kept.push(spec);
			}
			if (stripped.length > 0) {
				const parts = [];
				if (kept.length > 0) {
					const keptStr = kept.map((sp) => {
						const local = sp.local.name;
						const exported = sp.exported?.name ?? sp.exported?.value;
						return local === exported ? local : `${local} as ${exported}`;
					}).join(", ");
					parts.push(`export { ${keptStr} };`);
				}
				for (const name of stripped) parts.push(`export const ${name} = undefined;`);
				s.overwrite(node.start, node.end, parts.join("\n"));
				changed = true;
			}
		}
	}
	if (!changed) return null;
	return s.toString();
}
//#endregion
export { stripServerExports };

//# sourceMappingURL=strip-server-exports.js.map