# Linked bench recovery campaign

OPS-01 C7 uses the shared campaign planner and executor. The procedure
defaults plan 100 cases in a saved seeded order, with 20 single-node
memory checks and 80 paired known-data exchanges. Each linked batch has
at most 64 cases and a declared bound of at most 30 minutes. The matrix
checks that the batches contain exactly the ordered campaign list with
unique IDs, correct previous/next links and intact per-case evidence.

In **Experiments**, select **OPS-01**, **C7** and **Quick check** with
both roles connected and idle. Preview reports any missing capability.
The quick run has ten cases. Use **Inspect cases** and follow the
campaign export to verify its archive. A complete quick fixture
retains ten case results and 26 child records including file transfers.
Choose **Procedure defaults** to request the full 100-case campaign.

The matrix saves the underlying campaign reference before it starts
checking results. Stopping a run cancels the current child and retains
the partial campaign. The completed export is independently verified
before reporting a consistency result. Board disconnect/reset, host
restart, timeout and telemetry perturbation, loaded stability and the
full physical campaign acceptance remain separate cases.
