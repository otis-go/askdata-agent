//#region src/utils/manifest-paths.ts
function normalizeManifestFile(file) {
	return file.startsWith("/") ? file.slice(1) : file;
}
function manifestFileWithBase(file, base) {
	const normalizedFile = normalizeManifestFile(file);
	if (!base || base === "/") return normalizedFile;
	const normalizedBase = normalizeManifestFile(base).replace(/\/+$/, "");
	if (!normalizedBase) return normalizedFile;
	if (normalizedFile.startsWith(normalizedBase + "/")) return normalizedFile;
	return normalizedBase + "/" + normalizedFile;
}
function manifestFilesWithBase(files, base) {
	return files.map((file) => manifestFileWithBase(file, base));
}
//#endregion
export { manifestFileWithBase, manifestFilesWithBase, normalizeManifestFile };

//# sourceMappingURL=manifest-paths.js.map