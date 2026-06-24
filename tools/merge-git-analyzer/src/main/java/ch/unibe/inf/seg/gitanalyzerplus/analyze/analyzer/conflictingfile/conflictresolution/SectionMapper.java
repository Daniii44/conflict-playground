package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import java.util.ArrayList;

public class SectionMapper {

    /**
     * Determine whether the given lines in the sectionLines are found in the List of unmapped LineMapLists.
     *
     * @param unmappedLineMapLists segments of lines that are not mapped to a section (yet)
     * @param sectionLines         the lines to be found in the unmapped line segments
     * @return LineMapList containing the found lines and the corresponding section index, if successful, otherwise null
     */
    public static LineMapList findSectionContent(ArrayList<LineMapList> unmappedLineMapLists, String[] sectionLines) {
        // initialize variables
        int start = 0;
        int end = 0;
        int unmappedLineMapListLineIndex = 0;
        int sectionLineIndex = 0;
        LineMapList unmappedLineMapListWithMatch = null;

        // analyze all line map segments that are not yet mapped to a section
        for (LineMapList unmappedLineMapList : unmappedLineMapLists) {
            // break as soon as a match is found
            if (unmappedLineMapListWithMatch != null) break;
            // skip LineMapLists that do not have enough lines to hold the sectionLines
            if (sectionLines.length > unmappedLineMapList.size()) continue;

            // initialize the line index of this LineMapList
            unmappedLineMapListLineIndex = 0;
            // set the highest possible index that is used to traverse the unmapped LineMapList
            int unmappedLineMapListLineIndexMax = (unmappedLineMapList.size() - sectionLines.length);

            // try to find the sectionLines within the
            while (unmappedLineMapListWithMatch == null && unmappedLineMapListLineIndex <= unmappedLineMapListLineIndexMax) {

                // if the line of the unmapped LineMapList matches the first line of the sectionLines
                if (unmappedLineMapList.get(unmappedLineMapListLineIndex).line.equals(sectionLines[sectionLineIndex])) {
                    // set the start index
                    start = unmappedLineMapListLineIndex;

                    // while the lines match, increase the sectionLineIndex
                    while (sectionLineIndex < sectionLines.length && unmappedLineMapList.get(unmappedLineMapListLineIndex + sectionLineIndex).line.equals(sectionLines[sectionLineIndex])) {
                        sectionLineIndex++;
                    }

                    if (sectionLineIndex == sectionLines.length) {
                        // if all sectionLines were found in the unmapped LineMapList
                        unmappedLineMapListWithMatch = unmappedLineMapList;
                        end = start + sectionLineIndex;
                    } else {
                        // reset the sectionLineIndex for the next traversal
                        sectionLineIndex = 0;
                    }
                }
                unmappedLineMapListLineIndex++;
            }
        }

        if (unmappedLineMapListWithMatch != null) {
            LineMapList mappedLineSegment = new LineMapList();
            for (int i = start; i < end; i++) {
                mappedLineSegment.add(unmappedLineMapListWithMatch.get(i));
            }
            return mappedLineSegment;
        } else {
            return null;
        }
    }
}
