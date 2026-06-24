package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionList;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class LineMapListUtilsChunk2Test {

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
        return sectionListResult;
    }

    static SectionList sectionListResult() {
        SectionList sectionListResult = new SectionList();
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(0, 0, 0, 3, SectionType.CONTEXT));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(1, 1, 3, 6, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(2, 1, 6, 9, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(3, 1, 9, 12, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(4, 2, 12, 15, SectionType.CONTEXT));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(5, 3, 15, 18, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(6, 3, 18, 21, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(7, 3, 21, 24, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
        sectionListResult.add(new Section(8, 4, 24, 27, SectionType.CONTEXT));
        sectionListResult.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));

        return sectionListResult;
    }

    @Test
    void analyzeFirstContext_5() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(5).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(5).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeFirstContext_6() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(6).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(6).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeFirstContext_7() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(7).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(7).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeFirstContext_8() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(8).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(8).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeLastContext_3() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionAfterIndex = sectionList.get(3).getIndex();
        int sectionAfterStructureIndex = sectionList.get(3).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertTrue(sectionListResult.get(16).isUnmapped());
        assertTrue(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeLastContext_2() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionAfterIndex = sectionList.get(2).getIndex();
        int sectionAfterStructureIndex = sectionList.get(2).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertTrue(sectionListResult.get(16).isUnmapped());
        assertTrue(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeLastContext_1() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionAfterIndex = sectionList.get(1).getIndex();
        int sectionAfterStructureIndex = sectionList.get(1).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertTrue(sectionListResult.get(16).isUnmapped());
        assertTrue(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeLastContext_0() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionAfterIndex = sectionList.get(0).getIndex();
        int sectionAfterStructureIndex = sectionList.get(0).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertTrue(sectionListResult.get(16).isUnmapped());
        assertTrue(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNotNeighbouring_05() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(5).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(6).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(7).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNotNeighbouring_08() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(8).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNotNeighbouring_15() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(5).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(6).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(7).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(5).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(6).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(7).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(5).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(6).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());


        sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(7).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertFalse(sectionListResult.get(12).isUnmapped());
        assertFalse(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNotNeighbouring_18() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(8).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(8).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());

        sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();
        sectionAfterStructureIndex = sectionList.get(8).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
        assertTrue(sectionListResult.get(12).isUnmapped());
        assertTrue(sectionListResult.get(14).isUnmapped());
        assertFalse(sectionListResult.get(16).isUnmapped());
        assertFalse(sectionListResult.get(18).isUnmapped());
    }
}
