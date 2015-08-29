# Copyright (C) 2012 Robert Lanfear and Brett Calcott
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details. You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# PartitionFinder also includes the PhyML program, the RAxML program, and the
# PyParsing library, all of which are protected by their own licenses and
# conditions, using PartitionFinder implies that you agree with those licences
# and conditions as well.

"""Loading, Saving, Parsing Alignment Files

    See the phyml details here:
    http://www.atgc-montpellier.fr/phyml/usersguide.php?type=command

"""
import logtools
log = logtools.get_logger()

import os
from util import PartitionFinderError
import numpy
import cStringIO

# From the Phyml Website
# http://www.atgc-montpellier.fr/phyml/usersguide.php?type=command
valid_nucleotide = "AGCTUMRWSYKBDHVNX.-?"
valid_amino = "ARNBDCQZEGHILKMFPSTWYVX.-?"


class AlignmentError(PartitionFinderError):
    pass


class AlignmentParser(object):
    def __init__(self, stream, valid_bases=None):
        self.stream = stream
        self.current_line = 0
        self.cur_len = 0
        self.start_base = 0
        self.end_base = 0
        self.valid_bases = valid_bases
        self.block_len = None

        # This is the stuff we'll copy across
        self.species = []
        self.species_count = 0
        self.sequence_length = 0
        self.data = None

    def bases_to_array(self, bases=""):
        upper_bases = bases.upper()
        if self.valid_bases is not None:
            should_be_empty = upper_bases.translate(None, self.valid_bases)
            if should_be_empty != "":
                log.error("Line %d: Invalid bases '%s' found.",
                          self.current_line, should_be_empty)
                raise AlignmentError

        # Which is faster?
        # return array.array("B", upper_bases)
        return numpy.fromstring(upper_bases, dtype='u1')

    def parse(self):
        # Parse the header...
        self.parse_header()

        # We now know how big it is, so allocate the array.
        self.data = numpy.zeros((
            self.species_count,
            self.sequence_length
        ), 'u1')

        # Get the block with species in it
        self.parse_species_block()

        # Look for any further blocks
        while self.parse_interleave_block():
            pass

    def parse_header(self):
        while 1:
            line = self.stream.readline()
            self.current_line += 1

            if len(line) == 0:
                log.error("Line %d, Found no data in file", self.current_line)

            # Skip blank lines
            if len(line.strip()) == 0:
                continue

            # `split` works on whitespace
            bits = line.split()

            # We're looking for 2 bits, species count and bases
            if len(bits) == 2:
                # Convert them to integers
                S, C = map(int, bits)
                self.species_count = S
                self.sequence_length = C
                # We're done!
                return
            else:
                log.error("""Line %d: Failed to find the Phyml header that
                          specifies the species count, and sequence length""",
                          self.current_line)
                raise AlignmentError

    def check_block(self):
        # Do some checking on the line in the block
        if self.block_len is None:
            # Mark the length we got.
            self.block_len = self.cur_len
            self.end_base = self.start_base + self.block_len
            if self.end_base > self.sequence_length + 1:
                log.error("""Line %d: More supplied than defined in the
                            header""", self.current_line)
                raise AlignmentError
        else:
            # Make sure all species report the same length.
            if self.cur_len != self.block_len:
                log.error("""Line %d: Number of bases differs in length
                            from previous line(s)""", self.current_line)
                raise AlignmentError

    def parse_species_block(self):
        """Most sequences just have a block like this.

        Species1 ATCT
        Species2 ATCG
        ...
        """
        self.block_len = None

        # Look for species followed by bases, separated by whitespace.
        cur_species = 0
        while cur_species < self.species_count:
            line = self.stream.readline()
            self.current_line += 1

            if len(line) == 0:
                log.error("Line %d, Found no data in file", self.current_line)

            bits = line.split()
            num_bits = len(bits)
            if num_bits == 0:
                # Skip blanks lines
                continue

            # Should be two pieces -- [species, bases]
            if len(bits) != 2:
                log.error("""Line %d: Line should be species and bases
                          separated by whitespace""", self.current_line)
                raise AlignmentError

            spec, bases = bits
            self.cur_len = len(bases)

            self.check_block()
            self.species.append(spec)

            # Write into the array at the right position.
            arr = self.bases_to_array(bases)
            self.data[cur_species, self.start_base:self.end_base] = arr

            cur_species += 1

        self.start_base += self.block_len

    def parse_interleave_block(self):
        species_num = 0
        blank_lines = 0
        self.block_len = None

        while species_num < self.species_count:
            curline = self.stream.readline()
            self.current_line += 1
            self.cur_len = len(curline)

            if self.cur_len == 0:
                # If we read nothing, it is the end of the file
                if species_num != 0:
                    log.error("""Line %d: "Did not find enough lines for all
                              species in interleave block""",
                              self.current_line)
                    raise AlignmentError
                return False

            # Strip any whitespace
            bases = curline.strip()
            self.cur_len = len(bases)

            if self.cur_len == 0:
                # Skip blanks
                if species_num != 0:
                    log.error("""Line %d: Found blank line in interleave
                              block""", self.current_line)
                    raise AlignmentError

                blank_lines += 1
                continue

            if blank_lines == 0:
                log.error("""Line %d: Expected a blank line between blocks""",
                          self.current_line)
                raise AlignmentError

            self.check_block()

            arr = self.bases_to_array(bases)
            self.data[species_num, self.start_base:self.end_base] = arr

            species_num += 1

        self.start_base += self.block_len
        return True


class Alignment(object):
    def __init__(self):
        self.species = []
        self.sequence_length = 0
        self.data = None

    @property
    def species_count(self):
        return len(self.species)

    def __str__(self):
        return "Alignment(%s species, %s bases)"\
               % (self.species_count, self.sequence_length)

    def same_as(self, other):
        if self.sequence_length != other.sequence_length:
            log.warning("Alignments not the same, length differs %s: %s",
                        self.sequence_length, other.sequence_length)
            return False

        if self.species_count != other.species_count:
            log.warning("""Alignments not the same. This alignment has %s
                        species, the alignment from the previous  analysis had
                        %s.""",
                        len(self.species), len(other.species))
            return False

        if not (self.data == other.data).all():
            log.warning("Alignments not the same. Some of sequence differs.")
            return False

        return True

    def parse_stream(self, stream):
        p = AlignmentParser(stream)
        p.parse()

        # Copy everything from the import parser
        self.sequence_length = p.sequence_length
        self.species = p.species
        self.data = p.data

    def read(self, pth):
        log.info("Reading alignment file '%s'", pth)
        if not os.path.exists(pth):
            log.error("Cannot find alignment file '%s'", pth)
            raise AlignmentError

        with open(pth, 'rU') as stream:
            self.parse_stream(stream)

    def parse(self, text):
        stream = cStringIO.StringIO(text)
        self.parse_stream(stream)

    def write(self, pth):
        fd = open(pth, 'w')
        log.debug("Writing phylip file '%s'", pth)
        self.write_phylip(fd)
        fd.close()

    def write_phylip(self, stream):
        species_count = len(self.species)
        stream.write("%d %d\n" % (species_count, self.sequence_length))
        for i in range(species_count):
            spec = self.species[i]
            sequence = self.data[i]
            # We use a version of phylip which can have longer species names,
            # up to 100
            shortened = "%s    " % (spec[:99])
            stream.write(shortened)
            stream.write(sequence.tostring())
            stream.write("\n")


class SubsetAlignment(Alignment):
    """Create an alignment based on some others and a subset definition"""

    def __init__(self, source, subset):
        """create an alignment for this subset"""
        Alignment.__init__(self)

        # Let's do a basic check to make sure that the specified sites
        # aren't > alignment length
        site_max = max(subset.columns) + 1
        log.debug("Max site in data_blocks: %d; max site in alignment: %d"
                  % (site_max, source.sequence_length))
        if site_max > source.sequence_length:
            log.error("Site %d is specified in [data_blocks], "
                      "but the alignment only has %d sites. "
                      "Please check." % (site_max, source.sequence_length))
            raise AlignmentError

        self.species = source.species
        # Pull out the columns we need using the magic of numpy indexing
        self.data = source.data[:, subset.columns]
        self.sequence_length = len(subset.columns)
        assert self.sequence_length == self.data.shape[1]


class TestAlignment(Alignment):
    """Good for testing stuff"""
    def __init__(self, text):
        Alignment.__init__(self)
        self.parse(text)
