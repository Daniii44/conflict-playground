package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

/**
 * Denotes the type of section.
 */
public enum SectionType {
    UNMAPPED("UNMAPPED"),
    EMPTY("EMPTY"),
    CONTEXT("CONTEXT"),
    CHUNK_START("CHUNK_START"),
    CHUNK_OURS("CHUNK_OURS"),
    CHUNK_SEPARATOR_OURS_BASE("CHUNK_SEPARATOR_OURS_BASE"),
    CHUNK_BASE("CHUNK_BASE"),
    CHUNK_SEPARATOR_BASE_THEIRS("CHUNK_SEPARATOR_BASE_THEIRS"),
    CHUNK_THEIRS("CHUNK_THEIRS"),
    CHUNK_END("CHUNK_END");

    private final String typeString;

    SectionType(String typeString) {
        this.typeString = typeString;
    }

    @Override
    public String toString() {
        return this.typeString;
    }

    public boolean isChunkDelimiter() {
        return this.equals(CHUNK_START) || this.equals(CHUNK_SEPARATOR_OURS_BASE) || this.equals(CHUNK_SEPARATOR_BASE_THEIRS) || this.equals(CHUNK_END);
    }

    public boolean isChunk() {
        return this.equals(CHUNK_OURS) || this.equals(CHUNK_BASE) || this.equals(CHUNK_THEIRS);
    }

    public boolean isChunkOurs() {
        return this.equals(CHUNK_OURS);
    }

    public boolean isChunkBase() {
        return this.equals(CHUNK_BASE);
    }

    public boolean isChunkTheirs() {
        return this.equals(CHUNK_THEIRS);
    }

    public boolean isContext() {
        return this.equals(CONTEXT);
    }

    public boolean isUnmapped() {
        return this.equals(UNMAPPED);
    }
}