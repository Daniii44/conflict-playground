package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

/**
 * Denotes whether a section in the unmerged file was found in the merged one.
 */
public enum SectionMark {
    UNKNOWN("UNKNOWN"),
    NOT_FOUND("NOT_FOUND"),
    FOUND("FOUND");
    private final String typeString;

    SectionMark(String typeString) {
        this.typeString = typeString;
    }

    @Override
    public String toString() {
        return this.typeString;
    }
}