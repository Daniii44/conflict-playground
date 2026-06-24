package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

/**
 * Represents a line in a file that is mapped to a specific section. It includes the line itself ({@link #line}), the index it has in the file ({@link #index})
 * and the index of the section it belongs to ({@link #sectionIndex}).
 */
public class LineMap implements Comparable<LineMap> {

    protected final int index;
    protected final String line;
    protected int sectionIndex = -1;
    protected int sectionStructureIndex = -1;

    public LineMap(int index, String string) {
        this.index = index;
        this.line = string;
    }

    public boolean isNotMapped() {
        return sectionIndex == -1;
    }

    @Override
    public boolean equals(Object obj) {
        if (obj == this) return true;
        if (obj == null || obj.getClass() != this.getClass()) return false;
        var that = (LineMap) obj;
        return this.index == that.index;
    }

    @Override
    public int compareTo(LineMap that) {
        return Integer.compare(this.index, that.index);
    }
}