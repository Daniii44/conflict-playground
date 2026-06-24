package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionList;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionMark;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class LineMapListUtilsChunk3Test {

    static SectionList sectionList() {
        SectionList sectionListResult = new SectionList();
        sectionListResult.add(new Section(0, 0, 0, 3, SectionType.CONTEXT));
        sectionListResult.add(new Section(1, 1, 3, 6, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(2, 1, 6, 9, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(3, 1, 9, 12, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(4, 2, 12, 15, SectionType.CONTEXT));
        sectionListResult.add(new Section(5, 3, 15, 18, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(6, 3, 18, 21, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(7, 3, 21, 24, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(8, 4, 24, 27, SectionType.CONTEXT));
        sectionListResult.add(new Section(9, 5, 27, 30, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(10, 5, 30, 33, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(11, 5, 33, 36, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(12, 6, 36, 39, SectionType.CONTEXT));
        return sectionListResult;
    }

    static ArrayList<ArrayList<Integer>> generateFoundSectionIndices(SectionList sections, int[] indices) {
        ArrayList<ArrayList<Integer>> foundSectionIndices = new ArrayList<>();
        ArrayList<Integer> foundSectionIndicesIndices = new ArrayList<>();
        ArrayList<Integer> foundSectionIndicesStructureIndices = new ArrayList<>();
        for (int index : indices) {
            if (index != -1) {
                foundSectionIndicesIndices.add(sections.get(index).getIndex());
                foundSectionIndicesStructureIndices.add(sections.get(index).getStructureIndex());
            } else {
                foundSectionIndicesIndices.add(-1);
                foundSectionIndicesStructureIndices.add(-1);
            }
        }
        foundSectionIndices.add(foundSectionIndicesIndices);
        foundSectionIndices.add(foundSectionIndicesStructureIndices);
        return foundSectionIndices;
    }

    static void checkSectionListResult(SectionList sectionListResult, char[] mappingStatus) {
        assert sectionListResult.size() == mappingStatus.length;
        for (int i = 0; i < mappingStatus.length; i++) {
            checkMapping(sectionListResult.get(i), mappingStatus[i]);
        }
    }

    static void checkMapping(Section section, char mappingStatus) {
        if (mappingStatus == 'F') {
            assertTrue(section.isChunk() || section.isContext());
            assertEquals(SectionMark.FOUND, section.getSectionMark());
        } else if (mappingStatus == 'N') {
            assertTrue(section.isChunk() || section.isContext());
            assertEquals(SectionMark.NOT_FOUND, section.getSectionMark());
        } else if (mappingStatus == 'E') {
            assertEquals(SectionType.EMPTY, section.getSectionType());
        } else if (mappingStatus == 'U') {
            assertEquals(SectionType.UNMAPPED, section.getSectionType());
        } else {
            throw new IllegalArgumentException("Unknown mapping status!");
        }
    }

    @Test
    void analyzeSectionMapping_00() {
        int[] foundIndices = new int[]{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
        char[] mappingStatus = new char[]{'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E'};

        SectionList sectionList = sectionList();
        ArrayList<ArrayList<Integer>> foundSectionIndices = generateFoundSectionIndices(sectionList, foundIndices);
        SectionList sectionListResult = LineMapListUtils.calculateSectionList(sectionList, foundSectionIndices);
        checkSectionListResult(sectionListResult, mappingStatus);

    }

    @Test
    void analyzeSectionMapping_01() {
        int[] foundIndices = new int[]{-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
        char[] mappingStatus = new char[]{'U', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E', 'F', 'E'};
        SectionList sectionList = sectionList();
        ArrayList<ArrayList<Integer>> foundSectionIndices = generateFoundSectionIndices(sectionList, foundIndices);
        SectionList sectionListResult = LineMapListUtils.calculateSectionList(sectionList, foundSectionIndices);
        checkSectionListResult(sectionListResult, mappingStatus);
    }
}
