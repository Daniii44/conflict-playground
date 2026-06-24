package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionList;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;

import java.util.ArrayList;

public class LineMapList extends ArrayList<LineMap> {

    public LineMapList() {
        super();
    }

    /**
     * Get a list of all line map segments of unmapped lines.
     * Ex.: Suppose a LineMapList contains [0,1,...20] lines, of which lines 14-16 are mapped, and the rest are unmapped.
     * This function will return two LineMapLists [0,1,...13] and [17,18,...,20].
     *
     * @return list of all line segments containing unmapped lines
     */
    public ArrayList<LineMapList> getUnmappedLineSegments() {
        ArrayList<LineMapList> unmappedLineSegments = new ArrayList<>();
        int index = 0;
        while (index < this.size()) {
            if (this.get(index).isNotMapped()) {
                LineMapList unmappedLineSegment = new LineMapList();
                while (index < this.size() && this.get(index).isNotMapped()) {
                    unmappedLineSegment.add(this.get(index));
                    index++;
                }
                unmappedLineSegments.add(unmappedLineSegment);
            }
            index++;
        }
        return unmappedLineSegments;
    }

    /**
     * Get the sections indices of the
     *
     * @return
     */
    public ArrayList<ArrayList<Integer>> getFoundSectionIndicesIncludingUnmapped() {
        ArrayList<Integer> foundSectionIndices = new ArrayList<>();
        ArrayList<Integer> foundSectionStructureIndices = new ArrayList<>();
        int currentSectionIndex = -2;
        for (LineMap line : this) {
            if (currentSectionIndex != line.sectionIndex) {
                currentSectionIndex = line.sectionIndex;
                foundSectionIndices.add(line.sectionIndex);
                foundSectionStructureIndices.add(line.sectionStructureIndex);

            }
        }

        ArrayList<ArrayList<Integer>> foundIndices = new ArrayList<>();
        foundIndices.add(foundSectionIndices);
        foundIndices.add(foundSectionStructureIndices);

        return foundIndices;
    }

    public SectionList getSectionListFound(SectionList sections) {
        int currentSectionIndex = -2;
        int currentLineIndex = 0;
        SectionList sectionList = new SectionList();
        while (currentLineIndex < this.size()) {
            if (this.get(currentLineIndex).sectionIndex != currentSectionIndex) {
                currentSectionIndex = this.get(currentLineIndex).sectionIndex;
                Section section;
                if (currentSectionIndex == -1) {
                    section = new Section(-1, -1, currentLineIndex, currentLineIndex, SectionType.UNMAPPED);
                } else {
                    section = new Section(sections.get(currentSectionIndex).getIndex(), sections.get(currentSectionIndex).getStructureIndex(), currentLineIndex, currentLineIndex, sections.get(currentSectionIndex).getSectionType());
                }
                while (currentLineIndex < this.size() && this.get(currentLineIndex).sectionIndex == currentSectionIndex) {
                    currentLineIndex++;
                }
                section.setEnd(currentLineIndex);
                sectionList.add(section);
            }
        }
        return sectionList;
    }

}
