package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionAnalyzer;

import java.util.Objects;

/**
 * Represents a section within an unmerged file.
 * Each section has a beginning point ({@link #start}) and an end point ({@link #end}), and a {@link SectionType}.
 * Contexts are denoted by the SectionType {@link SectionType#CONTEXT}, and conflicting chunks are denoted by the following
 * section types (in order): {@link SectionType#CHUNK_START}, which denotes Git's merging marker 1, {@link SectionType#CHUNK_OURS},
 * which denotes the conflicting code lines found in the first parent file version, {@link SectionType#CHUNK_SEPARATOR_BASE_THEIRS},
 * which denotes Git's merging marker 2, {@link SectionType#CHUNK_THEIRS}, which denotes the conflicting code lines found
 * in the second parent file version, and {@link SectionType#CHUNK_END}, which denotes Git's merging marker 3.
 * After the {@link ConflictResolutionAnalyzer} is run, each section contains information about whether it was found (using {@link SectionMark}) and whether it was changed ({@link SectionState}).
 */
public class Section {

    protected SectionType sectionType;
    protected int index;
    protected int structureIndex;
    protected int start;
    protected int end;
    protected SectionMark sectionMark;

    public Section(int index, int structureIndex, int start, int end, SectionType sectionType, SectionMark sectionMark) {
        assert start <= end;
        this.index = index;
        this.structureIndex = structureIndex;
        this.start = start;
        this.end = end;
        this.sectionType = sectionType;
        this.sectionMark = sectionMark;
    }

    public Section(int index, int structureIndex, int start, int end, SectionType sectionType) {
        this(index, structureIndex, start, end, sectionType, SectionMark.UNKNOWN);
    }

    public Section(int start, int end, SectionType sectionType) {
        this(0, 0, start, end, sectionType, SectionMark.UNKNOWN);
    }

    public Section(int start, int end) {
        this(0, 0, start, end, SectionType.UNMAPPED, SectionMark.UNKNOWN);
    }

    public int getEnd() {
        return end;
    }

    public void setEnd(int end) {
        assert end >= 0;
        this.end = end;
    }

    public int getIndex() {
        return this.index;
    }

    public void setIndex(int index) {
        this.index = index;
    }

    public int getStructureIndex() {
        return this.structureIndex;
    }

    public void setStructureIndex(int structureIndex) {
        this.structureIndex = structureIndex;
    }

    public SectionType getSectionType() {
        return this.sectionType;
    }

    public void setSectionType(SectionType sectionType) {
        this.sectionType = sectionType;
    }

    public SectionMark getSectionMark() {
        return sectionMark;
    }

    public void setSectionMark(SectionMark sectionMark) {
        this.sectionMark = sectionMark;
    }

    public boolean isSectionType(SectionType sectionType) {
        return this.sectionType.equals(sectionType);
    }

    public boolean isEmpty() {
        return length() == 0;
    }

    public int length() {
        return Math.abs(end - start);
    }

    public String[] getContent(String[] fileContent) {
        assert start <= end;
        int length = end - start;
        assert length <= fileContent.length;
        assert 0 <= start && end <= fileContent.length;

        String[] sectionContent = new String[length];
        System.arraycopy(fileContent, start, sectionContent, 0, length);
        return sectionContent;
    }

    public boolean isChunkDelimiter() {
        return this.sectionType.isChunkDelimiter();
    }

    public boolean isChunk() {
        return this.sectionType.isChunk();
    }

    public boolean isChunkOurs() {
        return this.sectionType.isChunkOurs();
    }

    public boolean isChunkBase() {
        return this.sectionType.isChunkBase();
    }

    public boolean isChunkTheirs() {
        return this.sectionType.isChunkTheirs();
    }

    public boolean isContext() {
        return this.sectionType.isContext();
    }

    public boolean isUnmapped() {
        return this.sectionType.isUnmapped();
    }

    public boolean isFound() {
        return this.sectionMark.equals(SectionMark.FOUND);
    }

    @Override
    public Section clone() {
        if (this.sectionMark != null) {
            return new Section(this.index, this.structureIndex, this.start, this.end, this.sectionType, this.sectionMark);
        }
        return new Section(this.index, this.structureIndex, this.start, this.end, this.sectionType);
    }

    @Override
    public boolean equals(Object obj) {
        if (obj == this) return true;
        if (obj == null || obj.getClass() != this.getClass()) return false;
        var that = (Section) obj;
        return this.sectionType.equals(that.sectionType) && this.start == that.start && this.end == that.end;
    }

    @Override
    public int hashCode() {
        return Objects.hash(start, end, sectionType);
    }

    @Override
    public String toString() {
        return "Section[" +
                "index=" + this.index + ", " +
                "structureIndex=" + this.structureIndex + ", " +
                "start=" + this.start + ", " +
                "end=" + this.end + ", " +
                "sectionType=" + this.sectionType + ", " +
                "sectionMark=" + this.sectionMark +
                "]";
    }
}
