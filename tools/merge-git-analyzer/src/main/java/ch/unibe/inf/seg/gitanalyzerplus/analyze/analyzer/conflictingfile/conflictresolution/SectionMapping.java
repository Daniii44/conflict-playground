package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.*;

import java.util.ArrayList;

public class SectionMapping {
    protected final String[] unmergedFileStrings;
    protected SectionList unmergedFileSectionList;
    protected SectionList foundSectionList;
    protected LineMapList committedFileLines;
    protected SectionList committedFileSectionList;

    protected boolean hasSectionStructureChanged;

    protected ArrayList<ConflictResolutionResult> results;

    public SectionMapping(File unmergedFile, File mergedFile) {
        this.unmergedFileStrings = unmergedFile.getContent();
        this.unmergedFileSectionList = unmergedFile.getSections();
        this.committedFileLines = new LineMapList();
        this.results = new ArrayList<>();

        // add all lines
        for (int i = 0; i < mergedFile.getLength(); i++) {
            this.committedFileLines.add(new LineMap(i, mergedFile.getContent()[i]));
        }
    }

    public void calculate() {
        this.mapSections();
        this.hasSectionStructureChanged = this.isSectionStructureChanged();
        if (!this.hasSectionStructureChanged) {
            this.setResults();
        }
    }

    /**
     * Determine whether the sections from the unmerged file are found within the
     */
    private void mapSections() {
        // initialize all LineMapLists that are unmapped
        ArrayList<LineMapList> unmappedLineSegments = this.committedFileLines.getUnmappedLineSegments();

        // determine for each section whether it is found in the merged file
        for (Section section : this.unmergedFileSectionList) {
            if (!section.isEmpty()) {
                LineMapList mappedLineSegment = SectionMapper.findSectionContent(unmappedLineSegments, section.getContent(this.unmergedFileStrings));
                if (mappedLineSegment != null) {
                    // mark all found LineMaps as mapped
                    mappedLineSegment.forEach(ls -> {
                        ls.sectionIndex = section.getIndex();
                        ls.sectionStructureIndex = section.getStructureIndex();
                    });
                    unmappedLineSegments = this.committedFileLines.getUnmappedLineSegments();
                }
            }
        }
    }

    /**
     * @return the analysed section list
     */
    public ArrayList<ConflictResolutionResult> getResults() {
        return this.results;
    }

    public void setResults() {
        this.committedFileSectionList = LineMapListUtils.calculateSectionList(this.committedFileLines, this.unmergedFileSectionList);

        int i = 0;
        while (i < this.committedFileSectionList.size()) {
            if (i % 4 == 0) {
                Context context = new Context();

                context.add(this.committedFileSectionList.get(i));
                i++;
                context.add(this.committedFileSectionList.get(i));
                i++;
                context.add(this.committedFileSectionList.get(i));

                results.add(context.getConflictResolutionResult());
            } else {
                Chunk chunk = new Chunk();

                chunk.add(this.committedFileSectionList.get(i));
                i++;
                chunk.add(this.committedFileSectionList.get(i));
                i++;
                chunk.add(this.committedFileSectionList.get(i));
                i++;
                chunk.add(this.committedFileSectionList.get(i));
                i++;
                chunk.add(this.committedFileSectionList.get(i));

                results.add(chunk.getConflictResolutionResult());
            }
            i++;
        }
    }

    /**
     * Checks whether sections were mapped not in their original order.
     *
     * @return true if the structure of the found sections changed, false otherwise
     */
    private boolean isSectionStructureChanged() {
        foundSectionList = this.committedFileLines.getSectionListFound(this.unmergedFileSectionList);
        int currentSectionIndex = 0;
        for (Section foundSection : foundSectionList) {
            if (foundSection.getStructureIndex() != -1) {
                if (currentSectionIndex <= foundSection.getStructureIndex()) {
                    currentSectionIndex = foundSection.getStructureIndex();
                } else {
                    return true;
                }
            }
        }
        return false;
    }

    /**
     * Checks whether sections were mapped not in their original order.
     *
     * @return true if the structure of the found sections changed, false otherwise
     */
    public boolean hasSectionStructureChanged() {
        return this.hasSectionStructureChanged;
    }

}
