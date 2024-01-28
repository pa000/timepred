
from multiprocessing import Process, Queue
from typing import Generic, TypeVar


TIn = TypeVar("TIn")
TOut = TypeVar("TOut")

class ParallelManager(Generic[TIn, TOut]):
    def __init__(self, f, *args, nproc: int):
        self.nproc = nproc
        self.f = f
        self.in_queue: Queue[TIn] = Queue(1000)
        self.out_queue: Queue[TOut] = Queue(1000)

        for _ in range(nproc):
            p = Process(
                target=self._worker,
                args=args,
            )
            p.start()

    def put(self, input: TIn) -> None:
        self.in_queue.put(input)

    def get(self) -> TOut:
        return self.out_queue.get()

    def _worker(self, *args):
        while True:
            input = self.in_queue.get()

            result = self.f(input, *args)

            self.out_queue.put(result)
