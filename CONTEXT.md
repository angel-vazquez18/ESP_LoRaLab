# LoRa testbed language

A host-supervised laboratory bench for repeatable data and voice experiments
between embedded radio nodes.

## Language

**Device**: A physical embedded board with a persistent identity across resets
and USB reconnections. Its identity is independent of its assigned bench role.

**Node role**: The logical A or B assignment of a device within the bench.
Either role can transmit or receive in a particular experiment.

**Boot**: One continuous execution of a device's firmware between resets.
Measurements from different boots do not share an uptime clock.

**Session**: The temporary association of participating node roles, configuration
and security state for one run. A reset ends that association.

**Run**: One execution of a fully specified experiment case, with recorded
conditions, observations and an execution outcome.

**Campaign**: An ordered collection of experiment cases and repetitions, with
their runs and any blocked cases retained as evidence.

**Message**: The complete application content to be delivered, such as known
data or an encoded voice clip. It can require multiple fragments.

**Fragment**: A numbered slice of one message, reassembled before application
delivery. Receiving a duplicate fragment does not deliver the message again.

**Packet**: One original protocol frame prepared for radio transmission,
including its metadata and any protection. Retransmission preserves its identity.
_Avoid_: Using packet to mean a complete multi-fragment message.

**Transmission attempt**: One actual transmission of a packet over the radio.
The original transmission and each retry are separate attempts of the same packet.

**Accepted fragment**: A fragment that passes the configured integrity,
session, replay and message checks and enters reassembly exactly once.

**Delivered message**: A complete reconstructed message released to the
application after its required validation succeeds.

**Artifact**: Retained content associated with an experiment, such as reference
PCM, encoded speech or recovered audio, with identity and provenance.

**Execution outcome**: Whether a run completed, was blocked, failed, was
cancelled or was interrupted. It is separate from its experimental assessment.

**Assessment**: Whether recorded evidence passes or fails the case's assertions,
is inconclusive, or has not been assessed. Performance can be exploratory.

**Hardware evidence**: Observations from the required physical devices and
stages. Simulated observations exercise host behavior but do not close this evidence.
