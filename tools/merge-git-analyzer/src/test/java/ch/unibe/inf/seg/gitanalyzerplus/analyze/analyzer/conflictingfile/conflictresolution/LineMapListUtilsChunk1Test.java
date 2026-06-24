package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionList;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class LineMapListUtilsChunk1Test {

    static SectionList sectionList() {
        SectionList sectionListResult = new SectionList();
        sectionListResult.add(new Section(0, 0, 0, 3, SectionType.CONTEXT));
        sectionListResult.add(new Section(1, 1, 3, 6, SectionType.CHUNK_OURS));
        sectionListResult.add(new Section(2, 1, 6, 9, SectionType.CHUNK_BASE));
        sectionListResult.add(new Section(3, 1, 9, 12, SectionType.CHUNK_THEIRS));
        sectionListResult.add(new Section(4, 2, 12, 15, SectionType.CONTEXT));
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
        return sectionListResult;
    }

    @Test
    void analyzeFirstContext_0() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(0).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeFirstContext_1() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(1).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeFirstContext_2() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(2).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeFirstContext_3() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(3).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeFirstContext_4() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(4).getIndex();
        int sectionBeforeStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesBeforeFirstSection(sectionList, sectionListResult, sectionBeforeIndex, sectionBeforeStructureIndex);
        assertTrue(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeLastContext_4() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionAfterIndex = sectionList.get(4).getIndex();
        int sectionAfterStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesAfterLastSection(sectionList, sectionListResult, sectionAfterIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertTrue(sectionListResult.get(10).isUnmapped());
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
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_01() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(1).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_02() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(2).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_03() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(3).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertTrue(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_14() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(1).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_24() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(2).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices_34() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(3).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNeighbouringStructureIndices(sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertTrue(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());
    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsWithinChunk_12() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(1).getIndex();
        int sectionAfterIndex = sectionList.get(2).getIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsWithinChunk(sectionListResult, sectionBeforeIndex, sectionAfterIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertFalse(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());

    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsWithinChunk_13() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(1).getIndex();
        int sectionAfterIndex = sectionList.get(3).getIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsWithinChunk(sectionListResult, sectionBeforeIndex, sectionAfterIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());

    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsWithinChunk_23() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeIndex = sectionList.get(2).getIndex();
        int sectionAfterIndex = sectionList.get(3).getIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsWithinChunk(sectionListResult, sectionBeforeIndex, sectionAfterIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertFalse(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());

    }

    @Test
    void analyzeUnmappedLinesInBetweenSectionsNotNeighbouring_04() {
        SectionList sectionListResult = sectionListResult();
        SectionList sectionList = sectionList();

        int sectionBeforeStructureIndex = sectionList.get(0).getStructureIndex();
        int sectionAfterStructureIndex = sectionList.get(4).getStructureIndex();

        LineMapListUtils.analyzeUnmappedLinesInBetweenSectionsNotNeighbouringStructureIndices(sectionList, sectionListResult, sectionBeforeStructureIndex, sectionAfterStructureIndex);
        assertFalse(sectionListResult.get(0).isUnmapped());
        assertFalse(sectionListResult.get(2).isUnmapped());
        assertTrue(sectionListResult.get(4).isUnmapped());
        assertTrue(sectionListResult.get(6).isUnmapped());
        assertFalse(sectionListResult.get(8).isUnmapped());
        assertFalse(sectionListResult.get(10).isUnmapped());

    }
}