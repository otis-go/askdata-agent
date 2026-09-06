import fs from "node:fs";
import path from "node:path";
//#region src/entries/pages-entry-helpers.ts
/**
* Shared helpers used by the Pages Router entry generators.
*/
/**
* Find a file with any of the valid extensions in the given directory.
* Returns the first matching absolute path, or null if not found.
*/
function findFileWithExts(dir, name, matcher) {
	for (const ext of matcher.dottedExtensions) {
		const filePath = path.join(dir, name + ext);
		if (fs.existsSync(filePath)) return filePath;
	}
	return null;
}
//#endregion
export { findFileWithExts };

//# sourceMappingURL=pages-entry-helpers.js.map