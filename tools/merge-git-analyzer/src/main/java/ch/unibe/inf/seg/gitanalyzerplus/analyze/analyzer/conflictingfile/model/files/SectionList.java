package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

import java.util.ArrayList;

public class SectionList extends ArrayList<Section> {

    public SectionList() {
        super();
    }

    public SectionType getSectionTypeFromIndex(int index) {
        invariant();
        for (Section section : this) {
            if (section.getIndex() == index) {
                return section.sectionType;
            }
        }
        return SectionType.UNMAPPED;
    }

    public SectionType getSectionTypeFromStructureIndex(int structureIndex) {
        invariant();
        for (Section section : this) {
            if (section.getStructureIndex() == structureIndex) {
                return section.sectionType;
            }
        }
        return SectionType.UNMAPPED;
    }

    @Override
    public boolean equals(Object obj) {
        if (obj == this) return true;
        if (obj == null || obj.getClass() != this.getClass()) return false;
        var that = (SectionList) obj;
        if (this.size() != that.size()) return false;
        int index = 0;
        while (index < this.size()) {
            if (!this.get(index).equals(that.get(index))) {
                return false;
            }
            index++;
        }
        return true;
    }

    @Override
    public boolean contains(Object obj) {
        if (obj == null || obj.getClass() != Section.class) return false;
        var other = (Section) obj;
        for (Section section : this) {
            if (section.equals(other)) {
                return true;
            }
        }
        return false;
    }

    @Override
    public SectionList clone() {
        SectionList clone = new SectionList();
        for (Section section : this) {
            clone.add(section.clone());
        }
        return clone;
    }

    @Override
    public String toString() {
        StringBuilder stringBuilder = new StringBuilder();
        for (int i = 0; i < this.size(); i++) {
            stringBuilder.append(this.get(i).toString());
            if (i < this.size() - 1) {
                stringBuilder.append("\n");
            }
        }
        return stringBuilder.toString();
    }

    private void invariant() {
        assert this.size() == 0 || (this.size() % 4 == 1);
    }
}
