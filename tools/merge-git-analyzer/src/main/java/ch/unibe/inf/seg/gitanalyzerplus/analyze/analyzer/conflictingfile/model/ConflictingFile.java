package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.File;

import java.util.Objects;

/**
 * Represents a conflicting file.
 * Each conflicting file contains an unmerged file (the file which includes Git's merging markers as well as conflicting chunks and contexts),
 * and a merged file (the file that was committed to resolve the unmerged file).
 * <p>
 * The conflicting chunks of the conflicting file as well as every resolution files and the actual resolution files can be
 * retrieved from this class. Important to mention is that the resolution files can only be obtained iteratively to
 * reduce memory usage.
 */
public final class ConflictingFile {

    private final File mergedFile;
    private final File unmergedFile;
    private final String fileName;

    public ConflictingFile(File mergedFile, File unmergedFile, String fileName) {
        this.fileName = fileName;
        this.mergedFile = mergedFile;
        this.unmergedFile = unmergedFile;
        this.unmergedFile.calculateSections();
    }

    @Override
    public String toString() {
        return fileName;
    }

    @Override
    public boolean equals(Object obj) {
        if (obj == this) return true;
        if (obj == null || obj.getClass() != this.getClass()) return false;
        var that = (ConflictingFile) obj;
        return Objects.equals(this.mergedFile, that.mergedFile) &&
                Objects.equals(this.unmergedFile, that.unmergedFile) &&
                Objects.equals(this.fileName, that.fileName);
    }

    @Override
    public int hashCode() {
        return Objects.hash(mergedFile, unmergedFile, fileName);
    }

    public File mergedFile() {
        return mergedFile;
    }

    public File unmergedFile() {
        return unmergedFile;
    }

    public String fileName() {
        return fileName;
    }
}
