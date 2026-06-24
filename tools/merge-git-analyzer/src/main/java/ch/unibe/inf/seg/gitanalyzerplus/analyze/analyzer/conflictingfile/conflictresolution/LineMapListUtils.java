package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionList;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionMark;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;

import java.util.ArrayList;

public class LineMapListUtils {
    public static SectionList calculateSectionList(LineMapList lineMaps, SectionList sectionList) {
        ArrayList<ArrayList<Integer>> foundIndices = lineMaps.getFoundSectionIndicesIncludingUnmapped();
        return calculateSectionList(sectionList, foundIndices);
    }

    public static SectionList calculateSectionList(SectionList sectionList, ArrayList<ArrayList<Integer>> foundIndices) {
        int sectionListLength = getIndexForSectionListResult(sectionList.size());
        SectionList sectionListResult = new SectionList();
        for (int i = 0; i < sectionListLength; i++) {
            if (i % 2 == 0) {
                sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
            } else {
                int sectionIndex = (i - 1) / 2;
                Section foundSection = sectionList.get(sectionIndex).clone();
                if (foundIndices.get(0).contains(sectionIndex)) {
                    foundSection.setSectionMark(SectionMark.FOUND);
                } else {
                    foundSection.setSectionMark(SectionMark.NOT_FOUND);
                }
                sectionListResult.add(foundSection);
            }
        }

        if (foundIndices.get(0).contains(-1)) {
            return LineMapListUtils.handleUnmappedLines(sectionList, sectionListResult, foundIndices.get(0), foundIndices.get(1));
        }

        return sectionListResult;
    }

    protected static SectionList handleUnmappedLines(SectionList sectionList, SectionList sectionListResult, ArrayList<Integer> foundSectionIndicesIncludingUnmapped, ArrayList<Integer> foundSectionStructureIndicesIncludingUnmapped) {
        // handle completely unmapped files
        if (foundSectionIndicesIncludingUnmapped.size() == 1) {
            // handle files with only one chunk
            if (sectionList.size() == 5) {
                // set non-empty contexts to unmapped
                if (!sectionList.get(0).isEmpty()) {
                    sectionListResult.get(0).setSectionType(SectionType.UNMAPPED);
                    sectionListResult.get(2).setSectionType(SectionType.UNMAPPED);
                }
                if (!sectionList.get(4).isEmpty()) {
                    sectionListResult.get(8).setSectionType(SectionType.UNMAPPED);
                    sectionListResult.get(10).setSectionType(SectionType.UNMAPPED);
                }
                // set chunk as unmapped
                sectionListResult.get(4).setSectionType(SectionType.UNMAPPED);
                sectionListResult.get(6).setSectionType(SectionType.UNMAPPED);
            } else {
                sectionListResult.forEach(section -> {
                    if (section.isChunk() || section.isContext()) {
                        section.setSectionMark(SectionMark.NOT_FOUND);
                    } else {
                        section.setSectionType(SectionType.UNMAPPED);
                    }
                });
            }
        } else {
            // analyze unmapped segments at the beginning of the file
            if (foundSectionIndicesIncludingUnmapped.get(0) == -1) {
                int sectionAfterIndex = foundSectionIndicesIncludingUnmapped.get(1);
                int sectionAfterStructureIndex = foundSectionStructureIndicesIncludingUnmapped.get(1);
                analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
            }
            // analyze unmapped segments at the end of the file
            if (foundSectionIndicesIncludingUnmapped.get(foundSectionIndicesIncludingUnmapped.size() - 1) == -1) {
                int sectionBeforeIndex = foundSectionIndicesIncludingUnmapped.get(foundSectionIndicesIncludingUnmapped.size() - 2);
                int sectionBeforeStructureIndex = foundSectionStructureIndicesIncludingUnmapped.get(foundSectionStructureIndicesIncludingUnmapped.size() - 2);
                analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
            }
            // analyze other unmapped segments
            analyzeUnmappedLinesInBetweenSections(sectionList, sectionListResult, foundSectionIndicesIncludingUnmapped, foundSectionStructureIndicesIncludingUnmapped);
        }

        return sectionListResult;
    }

    /**
     * Determines whether lines were inserted before the first context.
     * This method is only called if after creating the mapping, there are still unmapped lines.
     */
    protected static void analyzeUnmappedLinesBeforeFirstSection(SectionList sectionList, SectionList sectionListResult, int sectionAfterIndex, int sectionAfterStructureIndex) {
        // check if the first section that was found is the first context
        if (sectionAfterIndex == sectionList.get(0).getIndex()) { // first context
            sectionListResult.get(0).setSectionType(SectionType.UNMAPPED);
        } else {
            int sectionAfterIndexLowest = getSectionIndexFromStructureIndex(sectionAfterStructureIndex, "lowest");

            int start = 0;
            int end;
            if (sectionList.getSectionTypeFromIndex(sectionAfterIndexLowest).equals(SectionType.CONTEXT)) { // context
                end = getIndexForSectionListResult(sectionAfterIndexLowest) - 3;
            } else {
                end = getIndexForSectionListResult(sectionAfterIndexLowest) - 1;
            }

            int i = start;
            while (i <= end) {
                sectionListResult.get(i).setSectionType(SectionType.UNMAPPED);
                i += 2;
            }
        }
    }

    /**
     * Determines whether lines were inserted after the last context.
     * This method is only called if after creating the mapping, there are still unmapped lines.
     */
    protected static void analyzeUnmappedLinesAfterLastSection(SectionList sectionList, SectionList sectionListResult, int sectionBeforeIndex, int sectionBeforeStructureIndex) {

        // check if the first section that was found is the first context
        if (sectionBeforeIndex == sectionList.get(sectionList.size() - 1).getIndex()) { // last context
            sectionListResult.get(sectionListResult.size() - 1).setSectionType(SectionType.UNMAPPED);
        } else {
            int start = sectionListResult.size() - 1;
            int sectionBeforeIndexHighest = getSectionIndexFromStructureIndex(sectionBeforeStructureIndex, "highest");

            int end;
            if (sectionList.getSectionTypeFromIndex(sectionBeforeIndexHighest).equals(SectionType.CONTEXT)) { // context
                end = getIndexForSectionListResult(sectionBeforeIndexHighest) + 3;
            } else {
                end = getIndexForSectionListResult(sectionBeforeIndexHighest) + 1;
            }

            int i = start;
            while (i >= end) {
                sectionListResult.get(i).setSectionType(SectionType.UNMAPPED);
                i -= 2;
            }
        }
    }

    /**
     * Analyzes where unmapped lines occur (in between which sections) and how to subsequently mark the sections
     * as either not found or changed.
     * This method is only called if after creating the mapping, there are still unmapped lines.
     */
    protected static void analyzeUnmappedLinesInBetweenSections(SectionList sectionList, SectionList sectionListResult, ArrayList<Integer> foundSectionIndicesIncludingUnmapped, ArrayList<Integer> foundSectionStructureIndicesIncludingUnmapped) {
        // analyze all sections except the first and last ones, since they are handled separately
        for (int i = 1; i < foundSectionIndicesIncludingUnmapped.size() - 1; i++) {
            if (foundSectionIndicesIncludingUnmapped.get(i) == -1) {
                int sectionBefore = foundSectionIndicesIncludingUnmapped.get(i - 1);
                int sectionAfter = foundSectionIndicesIncludingUnmapped.get(i + 1);
                int sectionBeforeStructureIndex = foundSectionStructureIndicesIncludingUnmapped.get(i - 1);
                int sectionAfterStructureIndex = foundSectionStructureIndicesIncludingUnmapped.get(i + 1);

                if (sectionBeforeStructureIndex == sectionAfterStructureIndex) { // within chunk
                    analyzeUnmappedLinesInBetweenSectionsWithinChunk(sectionListResult, sectionBefore, sectionAfter);
                } else if (sectionBeforeStructureIndex == sectionAfterStructureIndex - 1) { // sections with neighbouring structure indices
                    analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
                } else {
                    analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
                }
            }
        }
    }

    /**
     * Determines which neighbouring sections to mark as changed in the case of unmapped lines between them.
     *
     * @param sectionBefore the section before the unmapped lines
     * @param sectionAfter  the section after the unmapped lines
     */
    protected static void analyzeUnmappedLinesInBetweenSectionsWithinChunk(SectionList sectionListResult, int sectionBefore, int sectionAfter) {
        int sectionBeforeIndex = getIndexForSectionListResult(sectionBefore);
        int sectionAfterIndex = getIndexForSectionListResult(sectionAfter);

        int start = sectionBeforeIndex + 1;
        int end = sectionAfterIndex - 1;

        int i = start;
        while (i <= end) {
            sectionListResult.get(i).setSectionType(SectionType.UNMAPPED);
            i += 2;
        }
    }

    protected static void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(SectionList sectionListResult, int sectionBeforeStructureIndex, int sectionAfterStructureIndex) {
        int sectionBeforeIndex = getSectionIndexFromStructureIndex(sectionBeforeStructureIndex, "highest");
        int sectionAfterIndex = getSectionIndexFromStructureIndex(sectionAfterStructureIndex, "lowest");

        int start;
        int end;
        start = getIndexForSectionListResult(sectionBeforeIndex) + 1;
        end = getIndexForSectionListResult(sectionAfterIndex) - 1;

        int i = start;
        while (i <= end) {
            sectionListResult.get(i).setSectionType(SectionType.UNMAPPED);
            i += 2;
        }
    }

    protected static void analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(SectionList sectionList, SectionList sectionListResult, int sectionBeforeStructureIndex, int sectionAfterStructureIndex) {
        int sectionBeforeIndex = getSectionIndexFromStructureIndex(sectionBeforeStructureIndex, "highest");
        int sectionAfterIndex = getSectionIndexFromStructureIndex(sectionAfterStructureIndex, "lowest");

        int start;
        int end;
        if (sectionList.getSectionTypeFromStructureIndex(sectionBeforeStructureIndex).equals(SectionType.CONTEXT)) { // context
            start = getIndexForSectionListResult(sectionBeforeIndex) + 3;
        } else {
            start = getIndexForSectionListResult(sectionBeforeIndex) + 1;
        }
        if (sectionList.getSectionTypeFromStructureIndex(sectionAfterStructureIndex).equals(SectionType.CONTEXT)) { // context
            end = getIndexForSectionListResult(sectionAfterIndex) - 3;
        } else {
            end = getIndexForSectionListResult(sectionAfterIndex) - 1;
        }
        int i = start;
        while (i <= end) {
            sectionListResult.get(i).setSectionType(SectionType.UNMAPPED);
            i += 2;
        }
    }

    private static int getIndexForSectionListResult(int index) {
        return index * 2 + 1;
    }

    private static int getSectionIndexFromStructureIndex(int structureIndex, String placement) {
        if (structureIndex % 2 == 0) {
            return structureIndex * 2;
        } else {
            if (placement.equals("lowest")) {
                return structureIndex * 2 - 1;
            } else if (placement.equals("highest")) {
                return structureIndex * 2 + 1;
            } else {
                return structureIndex * 2;
            }
        }
    }
}
